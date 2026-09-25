"""Three axes that move independently, and refuse to be read as one.

Every test here would pass against a single `consent_state` enum if it only
checked the happy path. They are written to fail against one: each asserts
that two axes hold *contradictory-looking* values at the same instant, which
is exactly the state one column cannot represent.
"""

from datetime import datetime, timedelta, timezone

import pytest

from libs.contacts_consent import (
    Actor,
    AddressNotFound,
    ConsentEvidence,
    ContactsConsentRepository,
    PURPOSES,
    TenantScopeRequired,
)
from libs import contacts_consent as consent_module
from libs.contacts_repository import ContactsRepository
from tests.contacts.fake_postgres import FakeDatabase, FakeIntegrityError, FakeStore


TENANT = "org:acme"
OTHER_TENANT = "org:globex"

NOW = datetime(2026, 8, 4, 13, 15, tzinfo=timezone.utc)

MANAGER = Actor.human("principal:manager", ["manage_contacts"])
ADMIN = Actor.human("principal:admin", ["administer"])


def _setup(store=None, tenant=TENANT):
    """One person, one mobile, one mailbox, in one account."""
    db = FakeDatabase(store)
    contacts = ContactsRepository(db)
    consent = ContactsConsentRepository(db)
    org = contacts.create_branch(tenant, "Acme", kind="organization")
    person = contacts.create_contact(tenant, org["branch_id"], "Ana Perez")
    mobile = contacts.add_address(
        tenant, person["contact_id"], "sms", "+1 809 555-0100",
    )
    mailbox = contacts.add_address(
        tenant, person["contact_id"], "email", "Ana@Example.com",
    )
    return consent, contacts, db, person, mobile, mailbox


def _evidence(captured_at=NOW, method="web_form", expires_at=None):
    return ConsentEvidence(
        capture_method=method,
        captured_at=captured_at,
        captured_at_local="2026-08-04T09:15:00-04:00",
        capture_timezone="America/Santo_Domingo",
        jurisdiction="DO",
        disclosure_text=(
            "I agree to receive marketing text messages from Acme at the "
            "number provided. Consent is not a condition of purchase. "
            "Reply STOP to opt out."
        ),
        legal_basis="express_written",
        source="signup_form",
        default_unchecked=True,
        expires_at=expires_at,
    )


# -- the axes do not collapse ----------------------------------------------

def test_one_address_holds_a_valid_grant_and_a_suppression_at_the_same_time():
    consent, _contacts, _db, _person, mobile, _mailbox = _setup()
    address_id = mobile["address_id"]
    consent.activate_address(TENANT, address_id, MANAGER, now=NOW)
    consent.grant_consent(
        TENANT, address_id, "marketing", _evidence(), MANAGER, now=NOW,
    )

    # The carrier hard-bounces it an hour later. That is an operational fact
    # about the address; it is not the person changing their mind.
    consent.suppress(
        TENANT, address_id, "suppressed_by_bounce", reason_code="30003",
        now=NOW + timedelta(hours=1),
    )

    axes = consent.axes(TENANT, address_id, "sms", "marketing", now=NOW)
    assert axes["consent"]["state"] == "granted"
    assert axes["suppression"]["state"] == "suppressed_by_bounce"
    assert axes["usability"]["state"] == "active"
    assert axes["provider_reachability"]["state"] == "reachable"
    # The grant survives the bounce. A single enum would have had to pick one,
    # and picking the bounce destroys evidence the account is required to keep.
    assert axes["consent"]["disclosure_text"]
    assert axes["consent"]["legal_basis"] == "express_written"


def test_a_grant_on_one_channel_and_a_suppression_on_another_are_both_readable():
    consent, _contacts, _db, _person, mobile, mailbox = _setup()
    consent.activate_address(TENANT, mobile["address_id"], MANAGER, now=NOW)
    consent.activate_address(TENANT, mailbox["address_id"], MANAGER, now=NOW)
    consent.grant_consent(
        TENANT, mobile["address_id"], "marketing", _evidence(), MANAGER,
        now=NOW,
    )
    consent.suppress(
        TENANT, mailbox["address_id"], "suppressed_by_bounce",
        reason_code="hard_bounce", now=NOW,
    )

    assert consent.consent_state(
        TENANT, mobile["address_id"], "sms", "marketing", now=NOW,
    )["state"] == "granted"
    assert consent.suppression_state(
        TENANT, mobile["address_id"], "sms",
    )["state"] == "none"
    assert consent.suppression_state(
        TENANT, mailbox["address_id"], "email",
    )["state"] == "suppressed_by_bounce"
    # And the mailbox's own consent is untouched by its suppression.
    assert consent.consent_state(
        TENANT, mailbox["address_id"], "email", "marketing", now=NOW,
    )["state"] == "unknown"


def test_the_four_readings_disagree_with_each_other_and_all_four_survive():
    consent, _contacts, _db, _person, mobile, _mailbox = _setup()
    address_id = mobile["address_id"]
    consent.grant_consent(
        TENANT, address_id, "utility", _evidence(), MANAGER, now=NOW,
    )
    consent.suppress(
        TENANT, address_id, "suppressed_by_admin",
        now=NOW + timedelta(minutes=1),
    )

    axes = consent.axes(TENANT, address_id, "sms", "utility", now=NOW)

    # Granted, suppressed, not yet approved, and reachable -- four different
    # answers about one address at one instant. No single field can hold this,
    # which is the whole of KTD12 stated as an assertion.
    assert [
        axes["consent"]["state"],
        axes["suppression"]["state"],
        axes["usability"]["state"],
        axes["provider_reachability"]["state"],
    ] == ["granted", "suppressed_by_admin", "proposed", "reachable"]


# -- purpose scoping -------------------------------------------------------

def test_a_marketing_opt_out_does_not_block_a_transactional_effect():
    consent, _contacts, _db, _person, mobile, _mailbox = _setup()
    address_id = mobile["address_id"]
    consent.activate_address(TENANT, address_id, MANAGER, now=NOW)
    for purpose in ("marketing", "transactional"):
        consent.grant_consent(
            TENANT, address_id, purpose, _evidence(), MANAGER, now=NOW,
        )

    # A preference-centre unsubscribe, not a keyword. It withdraws one
    # purpose and creates no suppression, because suppression is the other
    # axis and blocking the channel here is the exact bug purpose scoping
    # exists to prevent.
    consent.record_opt_out(
        TENANT, address_id, "marketing", now=NOW + timedelta(hours=1),
    )

    later = NOW + timedelta(hours=2)
    marketing = consent.evaluate_eligibility(
        TENANT, address_id, "sms", "marketing", now=later,
    )
    transactional = consent.evaluate_eligibility(
        TENANT, address_id, "sms", "transactional", now=later,
    )

    assert not marketing.eligible
    assert marketing.reason == "consent_withdrawn"
    assert transactional.eligible
    assert transactional.reason == "eligible"
    # The channel itself was never blocked.
    assert consent.suppression_state(
        TENANT, address_id, "sms",
    )["state"] == "none"


# -- expiry ----------------------------------------------------------------

def test_consent_past_its_expiry_is_treated_as_absent():
    consent, _contacts, _db, _person, mobile, _mailbox = _setup()
    address_id = mobile["address_id"]
    consent.activate_address(TENANT, address_id, MANAGER, now=NOW)
    consent.grant_consent(
        TENANT, address_id, "marketing",
        _evidence(expires_at=NOW + timedelta(days=365)), MANAGER, now=NOW,
    )

    inside = NOW + timedelta(days=364)
    outside = NOW + timedelta(days=366)

    assert consent.consent_state(
        TENANT, address_id, "sms", "marketing", now=inside,
    )["state"] == "granted"
    lapsed = consent.consent_state(
        TENANT, address_id, "sms", "marketing", now=outside,
    )
    # Expired the instant it expired, not the next time a sweep happens to
    # run -- otherwise the width of the window in which a lapsed grant looks
    # live is whatever the batch schedule happens to be.
    assert lapsed["state"] == "expired"
    assert lapsed["recorded_state"] == "granted"
    assert not consent.evaluate_eligibility(
        TENANT, address_id, "sms", "marketing", now=outside,
    ).eligible
    assert consent.evaluate_eligibility(
        TENANT, address_id, "sms", "marketing", now=outside,
    ).reason == "consent_expired"


# -- usability is its own axis ---------------------------------------------

def test_a_new_address_is_unusable_until_somebody_decides_otherwise():
    consent, _contacts, _db, _person, mobile, _mailbox = _setup()
    address_id = mobile["address_id"]
    consent.grant_consent(
        TENANT, address_id, "marketing", _evidence(), MANAGER, now=NOW,
    )

    # A signed grant proves the person agreed. It does not prove the digits
    # are right, so the address stays unusable with no decision on file.
    assert consent.usability_state(TENANT, address_id)["state"] == "proposed"
    decision = consent.evaluate_eligibility(
        TENANT, address_id, "sms", "marketing", now=NOW,
    )
    assert not decision.eligible
    assert decision.reason == "address_not_usable"
    # And the reason names the axis that refused, not the first one anybody
    # thought to check.
    assert decision.axes["consent"]["state"] == "granted"


def test_eligibility_reports_the_most_fundamental_refusal_first():
    consent, _contacts, _db, _person, mobile, _mailbox = _setup()
    address_id = mobile["address_id"]
    consent.grant_consent(
        TENANT, address_id, "marketing", _evidence(), MANAGER, now=NOW,
    )
    consent.suppress(TENANT, address_id, "suppressed_by_bounce", now=NOW)

    # Unapproved *and* suppressed. An operator sent to the consent screen
    # would fix nothing, so usability answers first.
    assert consent.evaluate_eligibility(
        TENANT, address_id, "sms", "marketing", now=NOW,
    ).reason == "address_not_usable"

    consent.activate_address(
        TENANT, address_id, MANAGER, now=NOW + timedelta(minutes=1),
    )
    assert consent.evaluate_eligibility(
        TENANT, address_id, "sms", "marketing", now=NOW,
    ).reason == "suppressed_by_bounce"


def test_a_suppression_scoped_to_one_sender_leaves_other_senders_alone():
    consent, _contacts, _db, _person, mobile, _mailbox = _setup()
    address_id = mobile["address_id"]
    consent.suppress(
        TENANT, address_id, "suppressed_by_optout", sender_id="sender:promo",
        now=NOW,
    )

    # Twilio's STOP is scoped to the number the subscriber replied to.
    assert consent.suppression_state(
        TENANT, address_id, "sms", sender_id="sender:promo",
    )["state"] == "suppressed_by_optout"
    assert consent.suppression_state(
        TENANT, address_id, "sms", sender_id="sender:support",
    )["state"] == "none"


# -- retention -------------------------------------------------------------

def test_the_opt_out_decision_outlives_the_message_that_carried_it():
    consent, _contacts, _db, _person, mobile, _mailbox = _setup()
    address_id = mobile["address_id"]
    consent.record_inbound_opt_out(
        TENANT, address_id, keyword="STOP",
        message_body="STOP please stop texting me",
        content_ttl_seconds=30 * 24 * 60 * 60, now=NOW,
    )

    before = consent.consent_state(TENANT, address_id, "sms", "marketing", now=NOW)
    assert before["inbound_message_body"] == "STOP please stop texting me"
    # Five-year floor on the decision, thirty days on the body.
    assert before["retained_until"] == NOW.replace(year=NOW.year + 5)
    assert before["content_expires_at"] == NOW + timedelta(days=30)

    much_later = NOW + timedelta(days=40)
    purged = consent.purge_expired_content(TENANT, now=much_later)
    assert len(purged) == len(PURPOSES)

    after = consent.consent_state(
        TENANT, address_id, "sms", "marketing", now=much_later,
    )
    assert after["inbound_message_body"] is None
    assert after["content_purged_at"] == much_later
    # Everything that makes the opt-out defensible is still here. An opt-out
    # we cannot prove we honoured is indistinguishable from one we did not.
    assert after["state"] == "withdrawn"
    assert after["actor_kind"] == "contact"
    assert after["recorded_at"] == NOW
    assert after["source"] == "provider_webhook"
    assert after["retained_until"] > after["content_expires_at"]
    assert consent.suppression_state(
        TENANT, address_id, "sms",
    )["state"] == "suppressed_by_optout"


def test_recorded_consent_is_retained_longer_than_form_consent():
    consent, _contacts, _db, _person, mobile, _mailbox = _setup()
    address_id = mobile["address_id"]
    form = consent.grant_consent(
        TENANT, address_id, "marketing", _evidence(), MANAGER, now=NOW,
    )
    spoken = consent.grant_consent(
        TENANT, address_id, "utility",
        _evidence(method="voice_recording"), MANAGER, now=NOW,
    )

    # Five years is the floor. The recording *is* the evidence, so a dispute
    # at year six is answered by the recording or not at all.
    assert form["retained_until"] == NOW.replace(year=NOW.year + 5)
    assert spoken["retained_until"] == NOW.replace(year=NOW.year + 10)


def test_a_consent_record_cannot_be_rewritten_only_redacted():
    consent, _contacts, db, _person, mobile, _mailbox = _setup()
    address_id = mobile["address_id"]
    granted = consent.grant_consent(
        TENANT, address_id, "marketing", _evidence(), MANAGER, now=NOW,
    )
    consent.record_inbound_opt_out(
        TENANT, address_id, message_body="STOP", now=NOW + timedelta(hours=1),
    )
    withdrawal = consent.consent_state(
        TENANT, address_id, "sms", "marketing", now=NOW + timedelta(hours=1),
    )["consent_record_id"]

    # A purge job handed the wrong update statement is the realistic way the
    # evidence disappears, so every field that carries the decision or its
    # provenance is refused individually rather than trusted to a convention.
    for column, value, record_id in (
        ("state", "granted", withdrawal),
        ("disclosure_text", None, granted["consent_record_id"]),
        ("legal_basis", None, granted["consent_record_id"]),
        ("decided_by_principal_id", "principal:someone", granted["consent_record_id"]),
        ("retained_until", NOW, granted["consent_record_id"]),
        ("recorded_at", NOW, withdrawal),
    ):
        with db.transaction() as conn:
            db.set_org_context(conn, TENANT)
            with pytest.raises(FakeIntegrityError):
                conn.execute(
                    "update contacts.consent_records set %s = %%s "
                    "where tenant_id = %%s and consent_record_id = %%s"
                    % column,
                    (value, TENANT, record_id),
                )

    # And a redaction that forgets to stamp the purge, or leaves the body in
    # place, is refused for the same reason.
    with db.transaction() as conn:
        db.set_org_context(conn, TENANT)
        with pytest.raises(FakeIntegrityError):
            conn.execute(
                "update contacts.consent_records set content_purged_at = %s "
                "where tenant_id = %s and consent_record_id = %s",
                (NOW, TENANT, withdrawal),
            )


def test_a_suppression_ledger_entry_cannot_be_edited_after_the_fact():
    consent, _contacts, db, _person, mobile, _mailbox = _setup()
    address_id = mobile["address_id"]
    row = consent.suppress(TENANT, address_id, "suppressed_by_optout", now=NOW)

    with db.transaction() as conn:
        db.set_org_context(conn, TENANT)
        with pytest.raises(FakeIntegrityError):
            # "It was only a soft bounce" is a new row, not an edit.
            conn.execute(
                "update contacts.address_suppressions set state = %s "
                "where tenant_id = %s and suppression_id = %s",
                ("none", TENANT, row["suppression_id"]),
            )


# -- isolation -------------------------------------------------------------

def test_another_accounts_consent_is_not_readable_and_not_writable():
    store = FakeStore()
    consent, _contacts, _db, _person, mobile, _mailbox = _setup(store)
    other_consent, _o_contacts, _o_db, _o_person, other_mobile, _o_mailbox = \
        _setup(store, tenant=OTHER_TENANT)
    consent.activate_address(TENANT, mobile["address_id"], MANAGER, now=NOW)
    consent.grant_consent(
        TENANT, mobile["address_id"], "marketing", _evidence(), MANAGER,
        now=NOW,
    )
    other_consent.suppress(
        OTHER_TENANT, other_mobile["address_id"], "suppressed_by_bounce",
        now=NOW,
    )

    # Acme's grant is invisible to Globex, and reads as absence rather than
    # as a refusal that would confirm the row exists.
    assert other_consent.consent_state(
        OTHER_TENANT, mobile["address_id"], "sms", "marketing", now=NOW,
    )["state"] == "unknown"
    assert other_consent.suppression_state(
        OTHER_TENANT, mobile["address_id"], "sms",
    )["state"] == "none"
    assert other_consent.usability_state(
        OTHER_TENANT, mobile["address_id"],
    )["state"] == "proposed"
    # And a write against the other account's address does not resolve at all.
    with pytest.raises(AddressNotFound):
        other_consent.suppress(
            OTHER_TENANT, mobile["address_id"], "suppressed_by_admin", now=NOW,
        )
    # Acme still sees its own.
    assert consent.consent_state(
        TENANT, mobile["address_id"], "sms", "marketing", now=NOW,
    )["state"] == "granted"


def test_forced_row_level_security_is_the_backstop_when_a_predicate_is_lost():
    store = FakeStore()
    consent, _contacts, db, _person, mobile, _mailbox = _setup(store)
    _other, _o_contacts, _o_db, _o_person, _o_mobile, _o_mailbox = _setup(
        store, tenant=OTHER_TENANT,
    )
    consent.grant_consent(
        TENANT, mobile["address_id"], "marketing", _evidence(), MANAGER,
        now=NOW,
    )
    consent.record_inbound_opt_out(TENANT, mobile["address_id"], now=NOW)

    # The failure mode this guards is not a caller passing the wrong tenant --
    # that one denies itself. It is a future query written without the
    # predicate at all, which is why the statement below deliberately has
    # none.
    with db.connection() as conn:
        db.set_org_context(conn, OTHER_TENANT)
        for table, column, value in (
            ("contacts.consent_records", "channel", "sms"),
            ("contacts.address_suppressions", "channel", "sms"),
            ("contacts.address_usability_decisions", "state", "proposed"),
            ("contacts.provider_reachability_events", "channel", "sms"),
        ):
            assert conn.execute(
                "select tenant_id from %s where %s = %%s" % (table, column),
                (value,),
            ).fetchall() == []

    with db.connection() as conn:
        db.set_org_context(conn, TENANT)
        assert conn.execute(
            "select tenant_id from contacts.consent_records where channel = %s",
            ("sms",),
        ).fetchall()


def test_every_read_refuses_to_run_without_a_tenant():
    consent, _contacts, _db, _person, mobile, _mailbox = _setup()
    address_id = mobile["address_id"]

    for call in (
        lambda: consent.consent_state(None, address_id, "sms", "marketing"),
        lambda: consent.suppression_state(None, address_id, "sms"),
        lambda: consent.usability_state(None, address_id),
        lambda: consent.provider_reachability(None, address_id, "sms"),
        lambda: consent.purge_expired_content(None),
    ):
        # `tenant_id = null` matches nothing on a good day and everything on
        # the day somebody rewrites it as an optional filter.
        with pytest.raises(TenantScopeRequired):
            call()


# -- several rows, one instant ---------------------------------------------
#
# Every ledger in 0018 is read as "the newest row wins", and `recorded_at`
# ties as a matter of routine rather than as an edge case: one inbound STOP
# writes a withdrawal per purpose inside a single transaction under a single
# `now()`. So what breaks the tie decides real readings.
#
# It cannot be the identifier. These keys are ULIDs, and a ULID is ordered
# only across millisecond boundaries -- inside one, its low 80 bits are
# random. `_descending_identifiers` turns that randomness into its worst case
# and holds it there: each identifier issued sorts *below* the one before it,
# so a reader that tiebreaks on the identifier returns the oldest row on every
# run instead of the newest one on one run in N. The four tests that use it
# fail every time against an identifier tiebreak and never against an
# insertion-order one, which is the difference between a proof and a coin that
# came up heads.


@pytest.fixture
def descending_identifiers(monkeypatch):
    issued = {"n": 0}

    def issue():
        issued["n"] += 1
        return "%026d" % (10 ** 20 - issued["n"])

    monkeypatch.setattr(consent_module, "generate_ulid", issue)
    return issued


def test_a_stop_withdraws_every_purpose_granted_in_the_same_instant(
    descending_identifiers,
):
    """The case 0018 was written for, and the one that used to be a coin flip.

    A grant per purpose and then an inbound STOP, all under one `recorded_at`.
    Every purpose has two rows competing for "current", and the wrong answer
    is not a stale reading -- it is a person who texted STOP reading back as
    consenting to marketing.
    """
    consent, _contacts, _db, _person, mobile, _mailbox = _setup()
    address_id = mobile["address_id"]
    for purpose in PURPOSES:
        consent.grant_consent(
            TENANT, address_id, purpose, _evidence(), MANAGER, now=NOW,
        )

    reply = consent.record_inbound_opt_out(
        TENANT, address_id, message_body="STOP", now=NOW,
    )

    withdrawn = {
        row["purpose"]: row["consent_record_id"] for row in reply["consent"]
    }
    assert set(withdrawn) == set(PURPOSES)
    for purpose in PURPOSES:
        reading = consent.consent_state(
            TENANT, address_id, "sms", purpose, now=NOW,
        )
        assert reading["state"] == "withdrawn", purpose
        # Not merely "some withdrawal": the exact row the transaction wrote
        # last, so a reading that landed on the right state for the wrong
        # reason is still a failure.
        assert reading["consent_record_id"] == withdrawn[purpose], purpose


def test_the_ledger_sequence_belongs_to_the_store_and_never_to_the_caller():
    """`generated always as identity`, and load-bearing that it is.

    The sequence decides which row is current. A caller who could write it
    could make an old decision current without appending anything, which is
    the one thing an append-only ledger is for.
    """
    consent, _contacts, db, _person, mobile, _mailbox = _setup()
    row = consent.suppress(
        TENANT, mobile["address_id"], "suppressed_by_optout", now=NOW,
    )
    # It is also not part of what a caller is handed back: the ledger's
    # bookkeeping, not a field of the decision.
    assert "ledger_sequence" not in row

    with db.transaction() as conn:
        db.set_org_context(conn, TENANT)
        with pytest.raises(FakeIntegrityError):
            conn.execute(
                "insert into contacts.address_suppressions("
                "suppression_id, tenant_id, address_id, channel, state, "
                "transition_kind, source, actor_kind, retained_until, "
                "recorded_at, ledger_sequence"
                ") values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    "suppression:forged", TENANT, mobile["address_id"], "sms",
                    "suppressed_by_admin", "restrictive", "operator", "human",
                    NOW, NOW, 10 ** 9,
                ),
            )
        with pytest.raises(FakeIntegrityError):
            conn.execute(
                "update contacts.address_suppressions "
                "set ledger_sequence = %s "
                "where tenant_id = %s and suppression_id = %s",
                (10 ** 9, TENANT, row["suppression_id"]),
            )


def test_a_block_recorded_after_a_lift_in_the_same_instant_is_the_one_in_force(
    descending_identifiers,
):
    """The suppression ledger. Losing this one resumes sending to a blocked
    address, which is the failure the whole axis exists to prevent."""
    consent, _contacts, _db, _person, mobile, _mailbox = _setup()
    address_id = mobile["address_id"]
    consent.suppress(TENANT, address_id, "suppressed_by_optout", now=NOW)
    lifted = consent.lift_suppression(TENANT, address_id, ADMIN, now=NOW)
    blocked = consent.suppress(
        TENANT, address_id, "suppressed_by_bounce", reason_code="30003",
        now=NOW,
    )

    reading = consent.suppression_state(TENANT, address_id, "sms")
    assert reading["state"] == "suppressed_by_bounce"
    assert reading["suppression_id"] == blocked["suppression_id"]
    assert reading["suppression_id"] != lifted["suppression_id"]


def test_an_address_retired_in_the_instant_it_was_activated_reads_as_retired(
    descending_identifiers,
):
    """The usability ledger, whose restrictive direction is the fail-closed
    one: a retirement that loses the tie makes a withdrawn number sendable."""
    consent, _contacts, _db, _person, mobile, _mailbox = _setup()
    address_id = mobile["address_id"]
    consent.propose_address(TENANT, address_id, MANAGER, now=NOW)
    activated = consent.activate_address(TENANT, address_id, MANAGER, now=NOW)
    retired = consent.retire_address(
        TENANT, address_id, reason="wrong digits", now=NOW,
    )

    reading = consent.usability_state(TENANT, address_id)
    assert reading["state"] == "retired"
    assert reading["usability_decision_id"] == retired["usability_decision_id"]
    assert (
        reading["usability_decision_id"]
        != activated["usability_decision_id"]
    )


def test_the_newest_reachability_event_in_an_instant_is_the_one_read_back(
    descending_identifiers,
):
    """The reachability ledger. Two provider callbacks in one millisecond is
    an ordinary webhook redelivery, and the rows are identical apart from the
    keyword -- so nothing but insertion order can tell them apart."""
    consent, _contacts, _db, _person, mobile, _mailbox = _setup()
    address_id = mobile["address_id"]
    first = consent.record_provider_restart(
        TENANT, address_id, keyword="START", now=NOW,
    )
    second = consent.record_provider_restart(
        TENANT, address_id, keyword="UNSTOP", now=NOW,
    )

    reading = consent.provider_reachability(TENANT, address_id, "sms")
    assert reading["provider_keyword"] == "UNSTOP"
    assert reading["reachability_event_id"] == second["reachability_event_id"]
    assert reading["reachability_event_id"] != first["reachability_event_id"]


def test_the_tiebreak_holds_over_real_ulids_and_never_over_one_in_eight():
    """The same claim without the fixture, against the real generator.

    Twenty-five independent runs, eight withdrawals apiece under one
    `recorded_at`. An identifier tiebreak returns the row written last only
    when its random suffix happens to be the largest of the eight, so passing
    this by luck is roughly one chance in eight to the twenty-fifth. Insertion
    order passes it every time.
    """
    for _ in range(25):
        consent, _contacts, _db, _person, mobile, _mailbox = _setup()
        address_id = mobile["address_id"]
        written = [
            consent.record_opt_out(
                TENANT, address_id, "marketing",
                reason="attempt %d" % attempt, now=NOW,
            )[0]["consent_record_id"]
            for attempt in range(8)
        ]

        assert consent.consent_state(
            TENANT, address_id, "sms", "marketing", now=NOW,
        )["consent_record_id"] == written[-1]
