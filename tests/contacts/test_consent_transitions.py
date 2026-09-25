"""Who may move which axis, in which direction.

R12 says consent changes need an authorised human. R16 says an inbound
opt-out must suppress immediately. Read as symmetric rules they contradict
each other outright; the resolution is that they are not symmetric (KTD13).
Restrictive moves self-execute from whatever actor is at hand. Permissive
moves take a named human, and un-suppressing takes an administrator.

These tests are the enforcement. Each permissive path is attempted by every
actor that must not be able to take it, not only by the obviously wrong one.
"""

from datetime import datetime, timedelta, timezone

import pytest

from libs.contacts_consent import (
    Actor,
    AdministratorRequired,
    ConsentEvidence,
    ConsentEvidenceRequired,
    ContactsConsentRepository,
    CROSS_TOPIC_REVOCATION_EFFECTIVE,
    HumanDecisionRequired,
    PURPOSES,
    resolve_revocation_scope,
)
from libs.contacts_repository import ContactsRepository
from tests.contacts.fake_postgres import FakeDatabase


TENANT = "org:acme"

NOW = datetime(2026, 8, 4, 13, 15, tzinfo=timezone.utc)

MANAGER = Actor.human("principal:manager", ["manage_contacts"])
ADMIN = Actor.human("principal:admin", ["administer"])
#: An agent holding every authority in the set. Kind is what disqualifies it,
#: not permissions -- R12 makes the agent a proposer and never a decider.
AGENT = Actor.agent("principal:agent", ["manage_contacts", "administer"])
BYSTANDER = Actor.human("principal:viewer", ["read_contacts"])
SERVICE = Actor.system("principal:worker")


def _setup(tenant=TENANT):
    db = FakeDatabase()
    contacts = ContactsRepository(db)
    consent = ContactsConsentRepository(db)
    org = contacts.create_branch(tenant, "Acme", kind="organization")
    person = contacts.create_contact(tenant, org["branch_id"], "Ana Perez")
    mobile = contacts.add_address(
        tenant, person["contact_id"], "sms", "+18095550100",
    )
    return consent, mobile["address_id"]


def _evidence(captured_at=NOW, method="web_form", default_unchecked=True):
    return ConsentEvidence(
        capture_method=method,
        captured_at=captured_at,
        captured_at_local="2026-08-04T09:15:00-04:00",
        capture_timezone="America/Santo_Domingo",
        jurisdiction="DO",
        disclosure_text="I agree to receive marketing text messages from Acme.",
        legal_basis="express_written",
        source="signup_form",
        default_unchecked=default_unchecked,
    )


# -- restrictive moves self-execute ----------------------------------------

def test_an_inbound_opt_out_suppresses_immediately_with_no_human_step():
    consent, address_id = _setup()
    consent.activate_address(TENANT, address_id, MANAGER, now=NOW)
    consent.grant_consent(
        TENANT, address_id, "marketing", _evidence(), MANAGER, now=NOW,
    )

    # No actor argument, no approval, no queue. The provider webhook lands
    # and the block is in force on the next read.
    result = consent.record_inbound_opt_out(
        TENANT, address_id, keyword="STOP", message_body="STOP",
        now=NOW + timedelta(minutes=5),
    )

    at_once = NOW + timedelta(minutes=5)
    assert result["suppression"]["state"] == "suppressed_by_optout"
    assert result["suppression"]["transition_kind"] == "restrictive"
    assert result["suppression"]["decided_by_principal_id"] is None
    assert consent.suppression_state(
        TENANT, address_id, "sms",
    )["state"] == "suppressed_by_optout"
    decision = consent.evaluate_eligibility(
        TENANT, address_id, "sms", "marketing", now=at_once,
    )
    assert not decision.eligible
    assert decision.reason == "suppressed_by_optout"
    # A keyword is a statement about the channel, so every purpose goes.
    for purpose in PURPOSES:
        assert consent.consent_state(
            TENANT, address_id, "sms", purpose, now=at_once,
        )["state"] == "withdrawn"


def test_a_bounce_or_a_complaint_needs_no_authority_at_all():
    consent, address_id = _setup()

    for actor, state in (
        (SERVICE, "suppressed_by_bounce"),
        (Actor.provider(), "suppressed_by_provider"),
        (AGENT, "suppressed_by_admin"),
        (BYSTANDER, "suppressed_by_admin"),
    ):
        row = consent.suppress(
            TENANT, address_id, state, actor=actor, now=NOW,
        )
        assert row["state"] == state
        assert row["transition_kind"] == "restrictive"


def test_retiring_an_address_self_executes_but_activating_one_does_not():
    consent, address_id = _setup()

    retired = consent.retire_address(TENANT, address_id, actor=AGENT, now=NOW)
    assert retired["state"] == "retired"
    assert retired["transition_kind"] == "restrictive"
    assert consent.usability_state(TENANT, address_id)["state"] == "retired"
    assert consent.evaluate_eligibility(
        TENANT, address_id, "sms", "marketing", now=NOW,
    ).reason == "address_retired"

    with pytest.raises(HumanDecisionRequired):
        consent.activate_address(
            TENANT, address_id, AGENT, now=NOW + timedelta(minutes=1),
        )


# -- permissive moves take a human -----------------------------------------

def test_an_agent_cannot_grant_consent_however_many_authorities_it_holds():
    consent, address_id = _setup()

    with pytest.raises(HumanDecisionRequired):
        consent.grant_consent(
            TENANT, address_id, "marketing", _evidence(), AGENT, now=NOW,
        )
    with pytest.raises(HumanDecisionRequired):
        consent.grant_consent(
            TENANT, address_id, "marketing", _evidence(), SERVICE, now=NOW,
        )
    # A human with no authority over contacts is refused for the same reason
    # by a different half of the test: the check is kind *and* authority.
    with pytest.raises(HumanDecisionRequired):
        consent.grant_consent(
            TENANT, address_id, "marketing", _evidence(), BYSTANDER, now=NOW,
        )

    assert consent.consent_state(
        TENANT, address_id, "sms", "marketing", now=NOW,
    )["state"] == "unknown"


def test_an_agent_proposal_is_recorded_as_unproven_rather_than_as_consent():
    consent, address_id = _setup()
    consent.activate_address(TENANT, address_id, MANAGER, now=NOW)

    proposed = consent.propose_consent(
        TENANT, address_id, "marketing", AGENT, now=NOW,
    )

    assert proposed["state"] == "pending_evidence"
    assert proposed["transition_kind"] == "proposed"
    assert proposed["decided_by_principal_id"] is None
    # Visible in a review queue, and worth nothing to a dispatcher.
    assert consent.consent_state(
        TENANT, address_id, "sms", "marketing", now=NOW,
    )["state"] == "pending_evidence"
    decision = consent.evaluate_eligibility(
        TENANT, address_id, "sms", "marketing", now=NOW,
    )
    assert not decision.eligible
    assert decision.reason == "consent_missing"


def test_a_grant_without_the_evidence_it_would_be_defended_with_is_refused():
    consent, address_id = _setup()

    incomplete = ConsentEvidence(
        capture_method="web_form",
        captured_at=NOW,
        captured_at_local=None,
        jurisdiction=None,
        disclosure_text=None,
        legal_basis=None,
    )
    with pytest.raises(ConsentEvidenceRequired) as raised:
        consent.grant_consent(
            TENANT, address_id, "marketing", incomplete, MANAGER, now=NOW,
        )

    # The caller is told which part of the form was never captured, because
    # a grant recorded without it is worse than no grant: it looks like
    # permission.
    assert set(raised.value.missing) >= {
        "captured_at_local", "jurisdiction", "disclosure_text", "legal_basis",
        "default_unchecked",
    }
    assert consent.consent_state(
        TENANT, address_id, "sms", "marketing", now=NOW,
    )["state"] == "unknown"


def test_a_pre_ticked_box_is_not_consent():
    consent, address_id = _setup()

    with pytest.raises(ConsentEvidenceRequired) as raised:
        consent.grant_consent(
            TENANT, address_id, "marketing",
            _evidence(default_unchecked=False), MANAGER, now=NOW,
        )
    assert "default_unchecked" in raised.value.missing

    # And a form capture that simply never recorded the state of the box is
    # refused too -- silence is not proof.
    with pytest.raises(ConsentEvidenceRequired):
        consent.grant_consent(
            TENANT, address_id, "marketing",
            _evidence(default_unchecked=None), MANAGER, now=NOW,
        )


def test_a_recorded_call_needs_no_checkbox_proof():
    consent, address_id = _setup()

    granted = consent.grant_consent(
        TENANT, address_id, "marketing",
        _evidence(method="voice_recording", default_unchecked=None), MANAGER,
        now=NOW,
    )

    # There was no box. Demanding proof about one would make the recorded
    # path impossible rather than rigorous.
    assert granted["state"] == "granted"
    assert granted["default_unchecked"] is None
    assert granted["capture_method"] == "voice_recording"


def test_the_grant_carries_who_decided_and_under_which_authority():
    consent, address_id = _setup()

    granted = consent.grant_consent(
        TENANT, address_id, "marketing", _evidence(), MANAGER, now=NOW,
    )

    assert granted["transition_kind"] == "permissive"
    assert granted["actor_kind"] == "human"
    assert granted["decided_by_principal_id"] == "principal:manager"
    assert granted["decided_by_authority"] == "manage_contacts"
    # Both clocks, and the jurisdiction frozen at capture rather than read
    # from the contact's current one.
    assert granted["captured_at"] == NOW
    assert granted["captured_at_local"] == "2026-08-04T09:15:00-04:00"
    assert granted["jurisdiction"] == "DO"
    assert granted["disclosure_hash"]


# -- un-suppressing is narrower still --------------------------------------

def test_only_a_human_administrator_may_lift_a_suppression():
    consent, address_id = _setup()
    consent.suppress(TENANT, address_id, "suppressed_by_bounce", now=NOW)

    for actor in (AGENT, SERVICE, MANAGER, BYSTANDER, Actor.provider()):
        # Including the contact manager, who may grant consent and approve an
        # address and still may not resume sending to somebody who was
        # blocked.
        with pytest.raises(AdministratorRequired):
            consent.lift_suppression(TENANT, address_id, actor, now=NOW)

    assert consent.suppression_state(
        TENANT, address_id, "sms",
    )["state"] == "suppressed_by_bounce"

    lifted = consent.lift_suppression(
        TENANT, address_id, ADMIN, reason_code="verified_reachable",
        now=NOW + timedelta(days=1),
    )
    assert lifted["state"] == "none"
    assert lifted["transition_kind"] == "permissive"
    assert lifted["decided_by_authority"] == "administer"
    assert consent.suppression_state(
        TENANT, address_id, "sms",
    )["state"] == "none"


def test_lifting_a_suppression_does_not_resurrect_withdrawn_consent():
    consent, address_id = _setup()
    consent.activate_address(TENANT, address_id, MANAGER, now=NOW)
    consent.grant_consent(
        TENANT, address_id, "marketing", _evidence(), MANAGER, now=NOW,
    )
    # Two independent events: the person unsubscribes, and the address later
    # hard-bounces. Nothing here touches the carrier.
    consent.record_opt_out(
        TENANT, address_id, "marketing", now=NOW + timedelta(hours=1),
    )
    consent.suppress(
        TENANT, address_id, "suppressed_by_bounce",
        now=NOW + timedelta(hours=2),
    )

    consent.lift_suppression(
        TENANT, address_id, ADMIN, now=NOW + timedelta(days=1),
    )

    later = NOW + timedelta(days=2)
    assert consent.suppression_state(
        TENANT, address_id, "sms",
    )["state"] == "none"
    # The other axis never moved, and eligibility now fails on it instead.
    decision = consent.evaluate_eligibility(
        TENANT, address_id, "sms", "marketing", now=later,
    )
    assert not decision.eligible
    assert decision.reason == "consent_withdrawn"


# -- the provider is not a source of consent -------------------------------

def test_a_provider_restart_restores_reachability_without_restoring_consent():
    consent, address_id = _setup()
    consent.activate_address(TENANT, address_id, MANAGER, now=NOW)
    consent.grant_consent(
        TENANT, address_id, "marketing", _evidence(), MANAGER, now=NOW,
    )
    consent.record_inbound_opt_out(
        TENANT, address_id, keyword="STOP", now=NOW + timedelta(hours=1),
    )
    # Twilio blocked it too, and that block is what a START undoes.
    assert consent.provider_reachability(
        TENANT, address_id, "sms",
    )["state"] == "blocked_by_provider"

    # An administrator clears our own block, leaving only the carrier's.
    consent.lift_suppression(
        TENANT, address_id, ADMIN, now=NOW + timedelta(hours=2),
    )
    assert consent.evaluate_eligibility(
        TENANT, address_id, "sms", "marketing", now=NOW + timedelta(hours=3),
    ).reason == "provider_unreachable"

    # The subscriber texts START to reopen a support thread. Twilio resumes
    # delivery on its own; ACP-TASK gains nothing.
    restarted = consent.record_provider_restart(
        TENANT, address_id, keyword="START", now=NOW + timedelta(hours=4),
    )

    later = NOW + timedelta(hours=5)
    assert restarted["state"] == "reachable"
    assert restarted["provider_keyword"] == "START"
    axes = consent.axes(TENANT, address_id, "sms", "marketing", now=later)
    # Separately observable, and disagreeing: the carrier will carry it, and
    # we still may not send it.
    assert axes["provider_reachability"]["state"] == "reachable"
    assert axes["consent"]["state"] == "withdrawn"
    decision = consent.evaluate_eligibility(
        TENANT, address_id, "sms", "marketing", now=later,
    )
    assert not decision.eligible
    assert decision.reason == "consent_withdrawn"


def test_re_opt_in_takes_fresh_evidence_and_a_human_not_a_keyword():
    consent, address_id = _setup()
    consent.activate_address(TENANT, address_id, MANAGER, now=NOW)
    consent.record_inbound_opt_out(TENANT, address_id, now=NOW)
    consent.record_provider_restart(
        TENANT, address_id, keyword="START", now=NOW + timedelta(hours=1),
    )
    consent.lift_suppression(
        TENANT, address_id, ADMIN, now=NOW + timedelta(hours=2),
    )

    # The keyword and the lift together still leave consent withdrawn.
    assert consent.consent_state(
        TENANT, address_id, "sms", "marketing", now=NOW + timedelta(hours=3),
    )["state"] == "withdrawn"
    with pytest.raises(HumanDecisionRequired):
        consent.grant_consent(
            TENANT, address_id, "marketing", _evidence(), AGENT,
            now=NOW + timedelta(hours=3),
        )

    fresh = NOW + timedelta(days=30)
    regranted = consent.grant_consent(
        TENANT, address_id, "marketing", _evidence(captured_at=fresh), MANAGER,
        now=fresh,
    )

    assert regranted["state"] == "granted"
    # Dated after the withdrawal, not carried over from the original grant.
    assert regranted["captured_at"] == fresh
    assert consent.evaluate_eligibility(
        TENANT, address_id, "sms", "marketing", now=fresh,
    ).eligible


# -- revocation scope widens without a migration ---------------------------

def test_revocation_scope_widens_by_configuration_and_then_by_date():
    # Per-program today: unsubscribing from marketing leaves the delivery
    # notification alone.
    assert resolve_revocation_scope(NOW) == "program"
    # An account that wants the wider reading early flips a setting. All
    # three values are already legal in the column, so nothing migrates.
    assert resolve_revocation_scope(NOW, "cross_topic") == "cross_topic"
    # And from the duty date the floor is cross-topic whatever the setting
    # says, because the deadline is not something an operator opts out of by
    # forgetting to change it.
    after_duty = CROSS_TOPIC_REVOCATION_EFFECTIVE + timedelta(days=1)
    assert resolve_revocation_scope(after_duty, "program") == "cross_topic"


def test_a_program_scoped_opt_out_reaches_one_purpose_and_a_topic_one_reaches_its_topic():
    consent, address_id = _setup()

    consent.record_opt_out(TENANT, address_id, "marketing", now=NOW)
    assert consent.consent_state(
        TENANT, address_id, "sms", "marketing", now=NOW,
    )["state"] == "withdrawn"
    assert consent.consent_state(
        TENANT, address_id, "sms", "transactional", now=NOW,
    )["state"] == "unknown"

    later = NOW + timedelta(hours=1)
    consent.record_opt_out(
        TENANT, address_id, "transactional", revocation_scope="topic",
        now=later,
    )
    # Transactional, service, and utility share the operational topic;
    # authentication does not, and a locked-out user still gets their code.
    for purpose in ("transactional", "service", "utility"):
        assert consent.consent_state(
            TENANT, address_id, "sms", purpose, now=later,
        )["state"] == "withdrawn"
    assert consent.consent_state(
        TENANT, address_id, "sms", "authentication", now=later,
    )["state"] == "unknown"


def test_a_cross_topic_revocation_reaches_every_purpose_after_the_duty_date():
    consent, address_id = _setup()
    after_duty = CROSS_TOPIC_REVOCATION_EFFECTIVE + timedelta(days=1)

    written = consent.record_opt_out(
        TENANT, address_id, "marketing", now=after_duty,
    )

    assert len(written) == len(PURPOSES)
    for purpose in PURPOSES:
        reading = consent.consent_state(
            TENANT, address_id, "sms", purpose, now=after_duty,
        )
        assert reading["state"] == "withdrawn"
        assert reading["revocation_scope"] == "cross_topic"
