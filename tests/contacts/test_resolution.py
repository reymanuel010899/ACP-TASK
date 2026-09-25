"""Resolution that refuses to guess, and a queue that refuses to leak.

Every test here is written against the failure it prevents rather than the
feature it exercises, because the features all "work" while the failures are
present. A resolver that picks the first row resolves beautifully; it just
sometimes texts the wrong person. A candidate that carries a raw number
renders beautifully; it just hands the destination to whoever can see the
screen. So the assertions are about absence as much as presence: the digits
are not in the payload, the second account's namesake is not in the set, the
proposed number is not among the destinations, and the ambiguous run does not
produce a binding.
"""

from datetime import datetime, timedelta, timezone

import pytest

from agents.orchestrator.contacts_resolution import (
    CONFIRMATION_WINDOW,
    ContactResolver,
    MATCHED_BY_RECENT_CONFIRMATION,
    REASON_CONFIRMATION_CONFLICT,
    REASON_CONFIRMATION_NOT_POLICY_COMPATIBLE,
    REASON_CONFIRMATION_STALE,
    REASON_CONFIRMATION_TIE,
    REASON_MULTIPLE_MATCHES,
    RESOLVER_OUTCOMES,
    ResolutionBlocked,
    fold,
)
from libs.contacts_consent import (
    AUTHORITY_ADMINISTER,
    AUTHORITY_MANAGE_CONTACTS,
    Actor,
    ConsentEvidence,
    ContactsConsentRepository,
    HumanDecisionRequired,
)
from libs.contacts_permissions import (
    BranchPermissionsRepository,
    ContactsAccess,
    DIMENSION_VIEW,
)
from libs.contacts_proposals import (
    AddressCaptureBook,
    ProposalIncomplete,
    ProposalQueue,
    StaleRecord,
    UnsupportedProposal,
)
from libs.contacts_repository import ContactsRepository, record_version
from tests.contacts.fake_postgres import FakeDatabase, FakeStore


TENANT = "org:acme"
OTHER_TENANT = "org:globex"

ADMIN = Actor.human("principal:admin", [AUTHORITY_ADMINISTER])
REVIEWER = Actor.human("principal:reviewer", [AUTHORITY_MANAGE_CONTACTS])
AGENT = Actor.agent("agent:concierge")
ANALYST = "principal:analyst"

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
#: A human decides after the agent proposed, so the fixture reads the way the
#: thing it stands for happens. Not a workaround: U6's ledgers break a
#: `recorded_at` tie on `ledger_sequence`, so two decisions sharing one
#: timestamp resolve in the order they were written either way.
LATER = NOW + timedelta(hours=1)


def evidence(expires_at=None):
    return ConsentEvidence(
        capture_method="web_form",
        captured_at=NOW - timedelta(days=1),
        captured_at_local="2026-08-03T14:00:00",
        capture_timezone="Europe/Madrid",
        jurisdiction="ES",
        disclosure_text="Acepto recibir mensajes de Acme.",
        legal_basis="consent",
        default_unchecked=True,
        expires_at=expires_at,
    )


class Directory(object):
    """One account, one tree, one resolver, wired the way a service wires it."""

    def __init__(self, store=None, tenant=TENANT):
        self.tenant = tenant
        self.db = FakeDatabase(store)
        self.contacts = ContactsRepository(self.db)
        self.consent = ContactsConsentRepository(self.db)
        self.permissions = BranchPermissionsRepository(
            self.db, contacts=self.contacts,
        )
        self.access = ContactsAccess(
            self.db, contacts=self.contacts, permissions=self.permissions,
            consent=self.consent,
        )
        self.captures = AddressCaptureBook()
        self.queue = ProposalQueue(
            self.access, self.consent, contacts=self.contacts,
            captures=self.captures,
        )
        self.resolver = ContactResolver(
            self.access, contacts=self.contacts, consent=self.consent,
            clock=lambda: NOW,
        )
        self.org = self._branch("Acme", "organization", None)
        self.sales = self._branch("Sales", "department", self.org)
        self.finance = self._branch("Finance", "department", self.org)

    def _branch(self, name, kind, parent):
        return self.contacts.create_branch(
            self.tenant, name, kind=kind, parent_branch_id=parent,
        )["branch_id"]

    def see_everything(self, principal=ANALYST):
        self.permissions.grant(
            self.tenant, self.org, principal, DIMENSION_VIEW, ADMIN,
        )

    def see_only(self, branch_id, principal=ANALYST):
        self.permissions.grant(
            self.tenant, branch_id, principal, DIMENSION_VIEW, ADMIN,
        )

    def person(self, branch, name, channel="sms", address=None,
               active=True, granted="marketing", expires_at=None):
        contact = self.contacts.create_contact(self.tenant, branch, name)
        if address is None:
            return contact
        row = self.contacts.add_address(
            self.tenant, contact["contact_id"], channel, address,
            is_primary=True,
        )
        if active:
            self.consent.activate_address(
                self.tenant, row["address_id"], REVIEWER, now=NOW,
            )
        else:
            self.consent.propose_address(
                self.tenant, row["address_id"], AGENT, now=NOW,
            )
        if granted and active:
            self.consent.grant_consent(
                self.tenant, row["address_id"], granted,
                evidence(expires_at), REVIEWER, now=NOW,
            )
        return dict(contact, address_id=row["address_id"])

    def resolve(self, query, principal=ANALYST, **kwargs):
        return self.resolver.resolve(
            self.tenant, principal, query, **kwargs
        )


# -- finding the right person ----------------------------------------------

def test_a_spanish_request_naming_a_person_resolves_to_one_masked_candidate():
    directory = Directory()
    directory.see_everything()
    directory.person(directory.sales, "Ana Pérez", address="+34600111222")

    run = directory.resolve(
        "Ana Pérez", channel="sms", purpose="marketing",
    )

    assert run["outcome"] == "matched"
    assert run["outcome"] in RESOLVER_OUTCOMES
    (candidate,) = run["candidates"]
    assert candidate["display_name"] == "Ana Pérez"
    assert candidate["branch_path"].endswith("sales")
    (destination,) = candidate["destinations"]
    # The mask, not the number. Every rendering path downstream reads this
    # dict, so the digits being absent here is the whole guarantee.
    assert "600111222" not in str(destination)
    assert destination["country_code"] == "34"
    assert destination["fingerprint"]
    assert candidate["effect_ready"] is True
    assert candidate["consent"][
        list(candidate["consent"])[0]
    ]["eligible"] is True


def test_an_accented_name_is_found_by_someone_typing_without_accents():
    directory = Directory()
    directory.see_everything()
    directory.person(directory.sales, "Ana Pérez", address="+34600111222")

    assert directory.resolve("ana perez")["outcome"] == "matched"
    # One edit, which is the typo people actually make in a surname.
    assert directory.resolve("ana peres")["outcome"] == "matched"
    # Two edits is a different name, and a different name must not match.
    assert directory.resolve("ana lopez")["outcome"] == "not_found"


def test_a_stronger_match_never_shares_a_candidate_set_with_a_weaker_one():
    directory = Directory()
    directory.see_everything()
    directory.person(directory.sales, "Ana Perez", address="+34600111222")
    directory.person(directory.finance, "Ana Peres", address="+34600333444")

    run = directory.resolve("Ana Perez")

    assert run["outcome"] == "matched"
    assert [item["display_name"] for item in run["candidates"]] == ["Ana Perez"]


def test_a_person_in_two_lists_is_still_one_record_and_one_candidate():
    directory = Directory()
    directory.see_everything()
    ana = directory.person(
        directory.sales, "Ana Pérez", address="+34600111222",
    )
    vips = directory.contacts.create_list(TENANT, directory.sales, "VIPs")
    renewals = directory.contacts.create_list(
        TENANT, directory.sales, "Renewals",
    )
    directory.contacts.add_to_list(TENANT, vips["list_id"], ana["contact_id"])
    directory.contacts.add_to_list(
        TENANT, renewals["list_id"], ana["contact_id"],
    )
    before = len(directory.contacts.search_contacts(TENANT, ""))

    run = directory.resolve("Ana Pérez")

    assert run["outcome"] == "matched"
    assert [item["contact_id"] for item in run["candidates"]] == [
        ana["contact_id"]
    ]
    assert len(directory.contacts.search_contacts(TENANT, "")) == before


def test_two_accounts_holding_the_same_name_never_appear_in_one_set():
    store = FakeStore()
    acme = Directory(store, TENANT)
    globex = Directory(store, OTHER_TENANT)
    acme.see_everything()
    globex.see_everything()
    acme.person(acme.sales, "Ana Pérez", address="+34600111222")
    globex.person(globex.sales, "Ana Pérez", address="+34600999888")

    run = acme.resolve("Ana Pérez")

    assert run["outcome"] == "matched"
    (candidate,) = run["candidates"]
    assert candidate["branch_path"] == "/acme/sales"
    assert globex.resolve("Ana Pérez")["candidates"][0]["contact_id"] != \
        candidate["contact_id"]


def test_a_branch_the_requester_cannot_view_contributes_no_candidate():
    directory = Directory()
    directory.see_only(directory.sales)
    directory.person(directory.sales, "Ana Pérez", address="+34600111222")
    directory.person(directory.finance, "Ana Pérez", address="+34600333444")

    run = directory.resolve("Ana Pérez")

    assert run["outcome"] == "matched"
    assert run["candidates"][0]["branch_path"].endswith("sales")


def test_a_requester_with_no_visible_branch_learns_nothing_about_the_account():
    directory = Directory()
    directory.person(directory.sales, "Ana Pérez", address="+34600111222")

    run = directory.resolve("Ana Pérez")

    assert run["outcome"] == "not_found"
    assert run["candidates"] == ()


# -- refusing to guess ------------------------------------------------------

def test_two_people_of_the_same_name_block_with_the_candidate_set():
    directory = Directory()
    directory.see_everything()
    directory.person(directory.sales, "Ana Pérez", address="+34600111222")
    directory.person(directory.finance, "Ana Pérez", address="+34600333444")

    run = directory.resolve("Ana Pérez", channel="sms", purpose="marketing")

    assert run["outcome"] == "ambiguous"
    assert run["reason"] == REASON_MULTIPLE_MATCHES
    assert len(run["candidates"]) == 2
    assert {item["branch_path"] for item in run["candidates"]} == {
        "/acme/sales", "/acme/finance",
    }


def test_a_recent_human_confirmation_that_is_still_policy_compatible_wins():
    directory = Directory()
    directory.see_everything()
    chosen = directory.person(
        directory.sales, "Ana Pérez", address="+34600111222",
    )
    directory.person(directory.finance, "Ana Pérez", address="+34600333444")

    run = directory.resolve(
        "Ana Pérez", channel="sms", purpose="marketing",
        confirmations=[{
            "contact_id": chosen["contact_id"],
            "confirmed_at": NOW - timedelta(days=1),
        }],
    )

    assert run["outcome"] == "matched"
    assert run["matched_by"] == MATCHED_BY_RECENT_CONFIRMATION
    assert run["candidates"][0]["contact_id"] == chosen["contact_id"]


def test_a_recent_confirmation_whose_consent_has_expired_forces_the_question():
    directory = Directory()
    directory.see_everything()
    lapsed = directory.person(
        directory.sales, "Ana Pérez", address="+34600111222",
        expires_at=NOW - timedelta(days=2),
    )
    directory.person(directory.finance, "Ana Pérez", address="+34600333444")

    run = directory.resolve(
        "Ana Pérez", channel="sms", purpose="marketing",
        confirmations=[{
            "contact_id": lapsed["contact_id"],
            "confirmed_at": NOW - timedelta(hours=2),
        }],
    )

    # R13 permits preferring the confirmed match only while it remains policy
    # compatible. This is the case where the confirmation is most persuasive
    # and least safe, so it must not settle anything.
    assert run["outcome"] == "ambiguous"
    assert run["reason"] == REASON_CONFIRMATION_NOT_POLICY_COMPATIBLE
    assert len(run["candidates"]) == 2


def test_a_confirmation_older_than_the_window_stops_being_evidence():
    directory = Directory()
    directory.see_everything()
    chosen = directory.person(
        directory.sales, "Ana Pérez", address="+34600111222",
    )
    directory.person(directory.finance, "Ana Pérez", address="+34600333444")

    run = directory.resolve(
        "Ana Pérez", channel="sms", purpose="marketing",
        confirmations=[{
            "contact_id": chosen["contact_id"],
            "confirmed_at": NOW - CONFIRMATION_WINDOW - timedelta(days=1),
        }],
    )

    assert run["outcome"] == "ambiguous"
    assert run["reason"] == REASON_CONFIRMATION_STALE


def test_two_recent_confirmations_are_a_tie_and_not_a_tiebreak():
    directory = Directory()
    directory.see_everything()
    first = directory.person(
        directory.sales, "Ana Pérez", address="+34600111222",
    )
    second = directory.person(
        directory.finance, "Ana Pérez", address="+34600333444",
    )

    run = directory.resolve(
        "Ana Pérez", channel="sms", purpose="marketing",
        confirmations=[
            {"contact_id": first["contact_id"],
             "confirmed_at": NOW - timedelta(days=1)},
            {"contact_id": second["contact_id"],
             "confirmed_at": NOW - timedelta(hours=1)},
        ],
    )

    assert run["outcome"] == "ambiguous"
    assert run["reason"] == REASON_CONFIRMATION_TIE


def test_a_confirmation_for_somebody_outside_the_set_is_named_as_a_conflict():
    directory = Directory()
    directory.see_everything()
    directory.person(directory.sales, "Ana Pérez", address="+34600111222")
    directory.person(directory.finance, "Ana Pérez", address="+34600333444")
    elsewhere = directory.person(directory.finance, "Luis Gómez")

    run = directory.resolve(
        "Ana Pérez", channel="sms", purpose="marketing",
        confirmations=[{
            "contact_id": elsewhere["contact_id"],
            "confirmed_at": NOW - timedelta(hours=1),
        }],
    )

    assert run["outcome"] == "ambiguous"
    assert run["reason"] == REASON_CONFIRMATION_CONFLICT


# -- binding, and refusing to bind -----------------------------------------

def test_an_ambiguous_run_produces_no_binding_without_a_human_answer():
    directory = Directory()
    directory.see_everything()
    directory.person(directory.sales, "Ana Pérez", address="+34600111222")
    directory.person(directory.finance, "Ana Pérez", address="+34600333444")
    run = directory.resolve("Ana Pérez", channel="sms", purpose="marketing")

    with pytest.raises(ResolutionBlocked) as blocked:
        directory.resolver.materialize(run)

    assert blocked.value.outcome == "ambiguous"
    assert len(blocked.value.candidates) == 2


def test_selecting_a_candidate_binds_its_identifier_and_record_version():
    directory = Directory()
    directory.see_everything()
    ana = directory.person(
        directory.sales, "Ana Pérez", address="+34600111222",
    )
    directory.person(directory.finance, "Ana Pérez", address="+34600333444")
    run = directory.resolve("Ana Pérez", channel="sms", purpose="marketing")

    binding = directory.resolver.materialize(run, ana["contact_id"])

    assert binding["contact_id"] == ana["contact_id"]
    assert binding["record_version"]
    assert binding["effect_ready"] is True


def test_a_selection_nobody_offered_is_refused_rather_than_looked_up():
    directory = Directory()
    directory.see_everything()
    directory.person(directory.sales, "Ana Pérez", address="+34600111222")
    directory.person(directory.finance, "Ana Pérez", address="+34600333444")
    hidden = directory.person(directory.finance, "Luis Gómez")
    run = directory.resolve("Ana Pérez", channel="sms", purpose="marketing")

    with pytest.raises(ResolutionBlocked) as blocked:
        directory.resolver.materialize(run, hidden["contact_id"])

    assert blocked.value.reason == "selection_not_in_candidate_set"


def test_editing_the_bound_record_invalidates_the_pending_approval():
    directory = Directory()
    directory.see_everything()
    ana = directory.person(
        directory.sales, "Ana Pérez", address="+34600111222",
    )
    binding = directory.resolver.materialize(
        directory.resolve("Ana Pérez", channel="sms", purpose="marketing")
    )

    directory.contacts.move_contact(
        TENANT, ana["contact_id"], directory.finance,
    )
    after = directory.resolve("Ana Pérez", channel="sms", purpose="marketing")

    assert ContactResolver.binding_is_current(
        binding, after["candidates"][0]
    ) is False


def test_adding_a_second_number_also_invalidates_the_pending_approval():
    """The edit most likely to change who the message reaches.

    A move is obvious. A second number quietly added to the same person is the
    one that changes what a bound approval would dial, so the record version
    has to cover the addresses and not only the contact fields.
    """
    directory = Directory()
    directory.see_everything()
    ana = directory.person(
        directory.sales, "Ana Pérez", address="+34600111222",
    )
    binding = directory.resolver.materialize(
        directory.resolve("Ana Pérez", channel="sms", purpose="marketing")
    )

    directory.contacts.add_address(
        TENANT, ana["contact_id"], "sms", "+34600555666",
    )
    after = directory.resolve("Ana Pérez", channel="sms", purpose="marketing")

    assert ContactResolver.binding_is_current(
        binding, after["candidates"][0]
    ) is False


def test_a_lawful_consent_expiry_is_not_mistaken_for_an_edit():
    """KTD3, expressed as a hash boundary rather than a comment.

    Consent moving is not the record moving. If it entered the record version,
    every ordinary expiry would invalidate every pending approval and read as
    tampering.
    """
    directory = Directory()
    directory.see_everything()
    ana = directory.person(
        directory.sales, "Ana Pérez", address="+34600111222",
    )
    before = record_version(
        directory.contacts.get_contact(TENANT, ana["contact_id"]),
        directory.contacts.addresses(TENANT, ana["contact_id"]),
    )

    directory.consent.record_opt_out(
        TENANT, ana["address_id"], "marketing",
        actor=Actor.contact(), now=LATER,
    )

    assert record_version(
        directory.contacts.get_contact(TENANT, ana["contact_id"]),
        directory.contacts.addresses(TENANT, ana["contact_id"]),
    ) == before


# -- proposed data is not usable data --------------------------------------

def test_a_proposed_number_is_absent_from_resolution_until_a_human_approves():
    directory = Directory()
    directory.see_everything()
    ana = directory.person(
        directory.sales, "Ana Pérez", address="+34600111222", active=False,
    )

    run = directory.resolve("Ana Pérez", channel="sms", purpose="marketing")

    assert run["outcome"] == "matched"
    (candidate,) = run["candidates"]
    # Absent, not present-and-flagged. A destination a surface can render is a
    # destination somebody will try to use.
    assert candidate["destinations"] == []
    assert candidate["effect_ready"] is False

    directory.consent.activate_address(
        TENANT, ana["address_id"], REVIEWER, now=LATER,
    )
    directory.consent.grant_consent(
        TENANT, ana["address_id"], "marketing", evidence(), REVIEWER,
        now=LATER,
    )
    after = directory.resolve("Ana Pérez", channel="sms", purpose="marketing")

    assert len(after["candidates"][0]["destinations"]) == 1
    assert after["candidates"][0]["effect_ready"] is True


def test_a_resolver_without_a_consent_repository_treats_everything_as_unusable():
    directory = Directory()
    directory.see_everything()
    directory.person(directory.sales, "Ana Pérez", address="+34600111222")
    unconsented = ContactsAccess(
        directory.db, contacts=directory.contacts,
        permissions=directory.permissions, consent=None,
    )
    blind = ContactResolver(
        unconsented, contacts=directory.contacts, clock=lambda: NOW,
    )

    run = blind.resolve(TENANT, ANALYST, "Ana Pérez")

    assert run["candidates"][0]["destinations"] == []
    assert run["candidates"][0]["effect_ready"] is False


# -- the review queue ------------------------------------------------------

def test_an_agent_proposal_lands_unusable_and_a_human_makes_it_usable():
    directory = Directory()
    directory.see_everything()
    reference = directory.captures.capture(TENANT, "sms", "+34600111222")

    proposal = directory.queue.propose_contact(
        TENANT, ANALYST, AGENT, "Ana Pérez", directory.sales, "sms",
        reference, now=NOW,
    )

    assert proposal["state"] == "proposed"
    assert proposal["duplicate"] is False
    queued = directory.queue.pending(TENANT, ANALYST, now=NOW)
    assert [item["proposal_id"] for item in queued] == [
        proposal["proposal_id"]
    ]
    assert "600111222" not in str(queued[0]["destination"])
    assert directory.resolve(
        "Ana Pérez", channel="sms", purpose="marketing",
    )["candidates"][0]["effect_ready"] is False

    directory.queue.approve(
        TENANT, proposal["proposal_id"], REVIEWER,
        evidence=evidence(), purposes=("marketing",), now=LATER,
    )

    assert directory.queue.pending(TENANT, ANALYST, now=LATER) == []
    assert directory.resolve(
        "Ana Pérez", channel="sms", purpose="marketing",
    )["candidates"][0]["effect_ready"] is True


def test_approving_without_activating_would_leave_the_address_unusable():
    """The consequence U6 hands this unit, asserted rather than commented.

    An address with no usability decision reads as `proposed`. If approval
    only granted consent, the queue would empty and nothing would be sendable.
    """
    directory = Directory()
    directory.see_everything()
    reference = directory.captures.capture(TENANT, "sms", "+34600111222")
    proposal = directory.queue.propose_contact(
        TENANT, ANALYST, AGENT, "Ana Pérez", directory.sales, "sms",
        reference, now=NOW,
    )

    result = directory.queue.approve(
        TENANT, proposal["proposal_id"], REVIEWER,
        evidence=evidence(), purposes=("marketing",), now=LATER,
    )

    assert result["usability"]["state"] == "active"
    assert directory.consent.usability_state(
        TENANT, proposal["proposal_id"],
    )["state"] == "active"


def test_an_agent_cannot_approve_its_own_proposal():
    directory = Directory()
    directory.see_everything()
    reference = directory.captures.capture(TENANT, "sms", "+34600111222")
    proposal = directory.queue.propose_contact(
        TENANT, ANALYST, AGENT, "Ana Pérez", directory.sales, "sms",
        reference, now=NOW,
    )

    with pytest.raises(HumanDecisionRequired):
        directory.queue.approve(
            TENANT, proposal["proposal_id"], AGENT,
            evidence=evidence(), purposes=("marketing",), now=LATER,
        )


def test_a_claimed_consent_cannot_be_closed_by_activation_alone():
    directory = Directory()
    directory.see_everything()
    reference = directory.captures.capture(TENANT, "sms", "+34600111222")
    proposal = directory.queue.propose_contact(
        TENANT, ANALYST, AGENT, "Ana Pérez", directory.sales, "sms",
        reference, now=NOW,
    )
    directory.consent.propose_consent(
        TENANT, proposal["proposal_id"], "marketing", AGENT, now=NOW,
    )

    with pytest.raises(ProposalIncomplete):
        directory.queue.approve(
            TENANT, proposal["proposal_id"], REVIEWER, now=LATER,
        )


def test_proposing_the_same_number_twice_does_not_fill_the_queue():
    directory = Directory()
    directory.see_everything()
    first = directory.queue.propose_contact(
        TENANT, ANALYST, AGENT, "Ana Pérez", directory.sales, "sms",
        directory.captures.capture(TENANT, "sms", "+34600111222"), now=NOW,
    )

    second = directory.queue.propose_contact(
        TENANT, ANALYST, AGENT, "Ana Perez", directory.sales, "sms",
        directory.captures.capture(TENANT, "sms", "+34 600 111 222"), now=NOW,
    )

    assert second["duplicate"] is True
    assert second["proposal_id"] == first["proposal_id"]
    assert len(directory.queue.pending(TENANT, ANALYST, now=NOW)) == 1
    assert len(directory.contacts.search_contacts(TENANT, "")) == 1


def test_a_rejected_proposal_leaves_the_queue_and_stays_unusable():
    directory = Directory()
    directory.see_everything()
    proposal = directory.queue.propose_contact(
        TENANT, ANALYST, AGENT, "Ana Pérez", directory.sales, "sms",
        directory.captures.capture(TENANT, "sms", "+34600111222"), now=NOW,
    )

    directory.queue.reject(
        TENANT, proposal["proposal_id"], REVIEWER, reason="wrong number",
        now=LATER,
    )

    assert directory.queue.pending(TENANT, ANALYST, now=LATER) == []
    assert directory.consent.usability_state(
        TENANT, proposal["proposal_id"],
    )["state"] == "retired"
    assert directory.resolve(
        "Ana Pérez", channel="sms", purpose="marketing",
    )["candidates"][0]["destinations"] == []


def test_a_capture_from_another_account_cannot_be_redeemed():
    store = FakeStore()
    acme = Directory(store, TENANT)
    globex = Directory(store, OTHER_TENANT)
    reference = globex.captures.capture(OTHER_TENANT, "sms", "+34600999888")

    with pytest.raises(LookupError):
        acme.queue.propose_contact(
            TENANT, ANALYST, AGENT, "Ana Pérez", acme.sales, "sms",
            reference, now=NOW,
        )


def test_a_proposal_whose_channel_disagrees_with_the_capture_is_refused():
    directory = Directory()
    reference = directory.captures.capture(TENANT, "sms", "+34600111222")

    with pytest.raises(UnsupportedProposal):
        directory.queue.propose_contact(
            TENANT, ANALYST, AGENT, "Ana Pérez", directory.sales, "whatsapp",
            reference, now=NOW,
        )


def test_an_update_proposed_against_a_moved_record_is_refused_by_name():
    directory = Directory()
    directory.see_everything()
    ana = directory.person(
        directory.sales, "Ana Pérez", address="+34600111222",
    )
    stale = directory.resolve(
        "Ana Pérez", channel="sms", purpose="marketing",
    )["candidates"][0]["record_version"]
    directory.contacts.move_contact(
        TENANT, ana["contact_id"], directory.finance,
    )

    with pytest.raises(StaleRecord):
        directory.queue.propose_update(
            TENANT, ANALYST, AGENT, ana["contact_id"], stale,
            {"consent": {
                "address_id": ana["address_id"], "purpose": "marketing",
            }},
            now=NOW,
        )


def test_an_update_class_with_no_ledger_is_refused_rather_than_dropped():
    directory = Directory()
    directory.see_everything()
    ana = directory.person(
        directory.sales, "Ana Pérez", address="+34600111222",
    )
    current = directory.resolve(
        "Ana Pérez", channel="sms", purpose="marketing",
    )["candidates"][0]["record_version"]

    with pytest.raises(UnsupportedProposal):
        directory.queue.propose_update(
            TENANT, ANALYST, AGENT, ana["contact_id"], current,
            {"job_title": "Head of Sales"}, now=NOW,
        )


def test_a_proposed_consent_claim_is_visible_in_the_queue_and_is_not_consent():
    directory = Directory()
    directory.see_everything()
    ana = directory.person(
        directory.sales, "Ana Pérez", address="+34600111222", active=False,
        granted=None,
    )
    current = record_version(
        directory.contacts.get_contact(TENANT, ana["contact_id"]),
        directory.contacts.addresses(TENANT, ana["contact_id"]),
    )

    directory.queue.propose_update(
        TENANT, ANALYST, AGENT, ana["contact_id"], current,
        {"consent": {
            "address_id": ana["address_id"], "purpose": "marketing",
        }},
        now=NOW,
    )

    (queued,) = directory.queue.pending(TENANT, ANALYST, now=NOW)
    assert queued["pending_consent"] == ("marketing",)
    assert directory.consent.consent_state(
        TENANT, ana["address_id"], "sms", "marketing", now=NOW,
    )["state"] == "pending_evidence"


def test_folding_is_what_makes_the_query_hash_stable_across_spellings():
    directory = Directory()
    directory.see_everything()
    directory.person(directory.sales, "Ana Pérez", address="+34600111222")

    assert fold("  Ana   PÉREZ ") == "ana perez"
    assert directory.resolve("Ana Pérez")["query_hash"] == \
        directory.resolve("  ana perez ")["query_hash"]
