"""Import, and the directory a contact manager works without the agent.

Every test here is written so it would fail against the design this unit
replaces, which is: no design at all. The plan assumed import existed and
never built it, so the failure mode being guarded is not a subtle one -- it is
"a file becomes a reachable audience because nobody made it stop".

Three properties carry most of the weight, and each is asserted against what
is *absent* rather than only against what is returned:

* an imported address is unusable until a human activates it, asserted through
  `evaluate_eligibility` rather than through a state string, because the state
  string is what a future refactor would keep while losing the meaning;
* a claim of consent with no evidence leaves nothing behind at all -- not a
  flagged row, not a batch;
* and a destination never leaves the server unmasked for a principal without
  view, asserted against the whole payload, since a leak that only appears in
  a field nobody remembered to check is exactly the leak that ships.
"""

from datetime import datetime, timedelta, timezone

import pytest

from libs.contacts_consent import (
    AUTHORITY_ADMINISTER,
    AUTHORITY_MANAGE_CONTACTS,
    Actor,
    ConsentEvidence,
    ConsentEvidenceRequired,
    ContactsConsentRepository,
    HumanDecisionRequired,
)
from libs.contacts_import import (
    ContactDirectory,
    ContactImporter,
    ImportAlreadyDecided,
    ImportBatchNotFound,
    ImportRowInvalid,
    ImportRowNotFound,
    StaleContactRecord,
    UnsupportedRowDecision,
    canonical_address,
    read_delimited,
    to_e164,
)
from libs.contacts_permissions import (
    BranchPermissionsRepository,
    ContactsAccess,
    DIMENSION_ADMINISTER,
    DIMENSION_CAMPAIGN_USE,
    DIMENSION_EDIT,
    DIMENSION_VIEW,
    PermissionDenied,
)
from libs.contacts_repository import (
    ContactsRepository,
    normalize_channel_address,
)
from libs.tenancy import TenantScopeRequired
from tests.contacts.fake_postgres import (
    FakeDatabase,
    FakeIntegrityError,
    FakeStore,
)


TENANT = "org:acme"
OTHER_TENANT = "org:globex"

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)

ADMIN = Actor.human("principal:admin", [AUTHORITY_ADMINISTER])
MANAGER = Actor.human("principal:manager", [AUTHORITY_MANAGE_CONTACTS])
OPERATOR = Actor.human("principal:operator", [AUTHORITY_MANAGE_CONTACTS])
ROBOT = Actor.agent("agent:concierge", [AUTHORITY_ADMINISTER,
                                        AUTHORITY_MANAGE_CONTACTS])


def evidence(**overrides):
    """A complete, defensible consent bundle. Weakened per test on purpose."""
    fields = {
        "capture_method": "import_form",
        "captured_at": NOW - timedelta(days=3),
        "captured_at_local": "2026-08-02T14:00",
        "capture_timezone": "Europe/Madrid",
        "jurisdiction": "ES",
        "disclosure_text": "Acepto recibir mensajes comerciales de Acme.",
        "legal_basis": "consent",
        "default_unchecked": True,
        "source": "acme.example/alta",
    }
    fields.update(overrides)
    return fields


def claim(purposes=("marketing",), **overrides):
    bundle = evidence(**overrides)
    bundle["purposes"] = list(purposes)
    return bundle


def row(name, address, channel="sms", consent=None, **identity):
    entry = {"display_name": name, "channel": channel, "address": address}
    entry.update(identity)
    if consent is not None:
        entry["consent"] = consent
    return entry


class Account(object):
    """One account's tree, its authority, and the two surfaces under test."""

    def __init__(self, store=None, tenant=TENANT):
        self.tenant = tenant
        self.db = FakeDatabase(store)
        self.contacts = ContactsRepository(self.db)
        self.permissions = BranchPermissionsRepository(
            self.db, contacts=self.contacts,
        )
        self.consent = ContactsConsentRepository(self.db)
        self.access = ContactsAccess(
            self.db, contacts=self.contacts, permissions=self.permissions,
            consent=self.consent,
        )
        self.importer = ContactImporter(
            self.db, contacts=self.contacts, permissions=self.permissions,
            consent=self.consent, access=self.access, clock=lambda: NOW,
        )
        self.directory = ContactDirectory(
            self.db, contacts=self.contacts, permissions=self.permissions,
            consent=self.consent, access=self.access, clock=lambda: NOW,
        )
        self.org = self._branch("Acme", "organization", None)
        self.sales = self._branch("Sales", "department", self.org)
        self.iberia = self._branch("Iberia", "folder", self.sales)
        self.finance = self._branch("Finance", "department", self.org)
        for dimension in (DIMENSION_VIEW, DIMENSION_EDIT):
            self.permissions.grant(
                self.tenant, self.org, MANAGER.principal_id, dimension, ADMIN,
            )

    def _branch(self, name, kind, parent):
        return self.contacts.create_branch(
            self.tenant, name, kind=kind, parent_branch_id=parent,
        )["branch_id"]

    def person(self, branch, name, address, channel="sms"):
        contact = self.contacts.create_contact(self.tenant, branch, name)
        stored = self.contacts.add_address(
            self.tenant, contact["contact_id"], channel, address,
            is_primary=True,
        )
        return contact, stored

    def stage(self, rows, actor=MANAGER, branch=None, **kwargs):
        return self.importer.stage(
            self.tenant, actor, branch or self.sales, rows, **kwargs
        )

    def eligibility(self, address_id, channel="sms", purpose="marketing"):
        return self.consent.evaluate_eligibility(
            self.tenant, address_id, channel, purpose, now=NOW,
        )

    def contacts_named(self, query=""):
        return self.contacts.search_contacts(self.tenant, query)

    def address_of(self, contact_id):
        return self.contacts.addresses(self.tenant, contact_id)[0]


# -- canonical destinations -------------------------------------------------

def test_every_spelling_of_one_number_reduces_to_the_same_canonical_form():
    written = (
        "+1 809 555-0100",
        "+18095550100",
        "001 (809) 555 0100",
        "809-555-0100",
    )

    forms = {to_e164(value, default_calling_code="1") for value in written}

    assert forms == {"+18095550100"}


def test_a_national_number_with_no_calling_code_is_refused_not_guessed():
    with pytest.raises(ImportRowInvalid):
        to_e164("809-555-0100")


def test_a_national_number_keeping_its_trunk_zero_still_reduces():
    assert to_e164("0600 111 222", default_calling_code="34") == "+34600111222"


def test_the_canonical_form_is_the_form_the_directory_would_store():
    # The load-bearing invariant: dedupe compares on the same key the unique
    # constraint compares on. If these two ever diverge, two rows this module
    # calls identical get written as two addresses -- or one gets refused by a
    # constraint halfway through a batch nobody can re-run.
    for channel, written in (
        ("sms", "+1 809 555-0100"),
        ("whatsapp", "001 809 555 0100"),
        ("voice", "809 555 0100"),
        ("email", "  Ana@Example.COM "),
    ):
        canonical = canonical_address(channel, written, default_calling_code="1")

        assert normalize_channel_address(channel, canonical) == canonical


def test_read_delimited_uses_the_mapping_it_is_given_and_guesses_nothing():
    text = (
        "Nombre,Movil,consent_purposes,capture_method,captured_at,"
        "captured_at_local,jurisdiction,disclosure_text,legal_basis,"
        "default_unchecked\n"
        "Ana Pérez,+34600111222,marketing|service,import_form,"
        "2026-08-02T12:00:00+00:00,2026-08-02T14:00,ES,Acepto.,consent,true\n"
    )

    rows = read_delimited(text, mapping={"Nombre": "display_name",
                                         "Movil": "address"})

    assert rows[0]["display_name"] == "Ana Pérez"
    assert rows[0]["address"] == "+34600111222"
    assert rows[0]["consent"]["purposes"] == ["marketing", "service"]
    assert rows[0]["consent"]["default_unchecked"] is True
    assert rows[0]["consent"]["captured_at"] == datetime(
        2026, 8, 2, 12, 0, tzinfo=timezone.utc,
    )


# -- staging ----------------------------------------------------------------

def test_a_file_of_new_contacts_lands_as_one_canonical_record_each():
    account = Account()

    batch = account.stage([
        row("Ana Pérez", "+34600111222"),
        row("Bruno Díaz", "+34600111333"),
        row("Carmen Ruiz", "carmen@example.com", channel="email"),
    ])
    # Nothing is in the directory yet. Staging is not a write.
    assert account.contacts_named() == []
    assert batch["new_count"] == 3

    summary = account.importer.apply(TENANT, batch["batch_id"], MANAGER)

    assert summary["created"] == 3
    assert sorted(
        contact["display_name"] for contact in account.contacts_named()
    ) == ["Ana Pérez", "Bruno Díaz", "Carmen Ruiz"]


def test_the_same_person_written_two_ways_produces_one_canonical_record():
    account = Account()

    batch = account.stage(
        [
            row("Ana Pérez", "+1 809 555-0100"),
            row("Ana Perez", "809-555-0100"),
        ],
        default_calling_code="1",
    )
    account.importer.apply(TENANT, batch["batch_id"], MANAGER)

    assert batch["new_count"] == 1
    assert batch["duplicate_count"] == 1
    assert len(account.contacts_named()) == 1
    staged = account.importer.staged_rows(TENANT, batch["batch_id"])
    assert staged[1]["duplicate_of_row_id"] == staged[0]["import_row_id"]
    # The duplicate row settles against the record its twin produced, so an
    # applied batch reconciles row-for-row against the directory it created
    # rather than leaving a line nobody can account for.
    assert staged[1]["applied_contact_id"] == staged[0]["applied_contact_id"]
    assert staged[1]["applied_contact_id"] == account.contacts_named()[0][
        "contact_id"
    ]


def test_a_person_already_in_the_target_branch_is_a_duplicate_not_a_new_record():
    account = Account()
    existing, _ = account.person(account.iberia, "Ana Pérez", "+34600111222")

    batch = account.stage([row("Ana P.", "+34 600 111 222")])
    account.importer.apply(TENANT, batch["batch_id"], MANAGER)

    assert batch["duplicate_count"] == 1
    assert len(account.contacts_named()) == 1
    settled = account.importer.staged_rows(TENANT, batch["batch_id"])[0]
    assert settled["applied_contact_id"] == existing["contact_id"]


def test_an_address_held_outside_the_target_branch_raises_a_collision():
    account = Account()
    elsewhere, _ = account.person(account.finance, "Ana Pérez", "+34600111222")

    batch = account.stage([row("Ana P.", "+34600111222")])
    summary = account.importer.apply(TENANT, batch["batch_id"], MANAGER)

    assert batch["collision_count"] == 1
    # Not merged, not duplicated, not created: deferred to a person.
    assert summary["created"] == 0
    assert summary["deferred"] == 1
    assert len(account.contacts_named()) == 1
    staged = account.importer.staged_rows(TENANT, batch["batch_id"])[0]
    assert staged["state"] == "staged"
    assert staged["matched_contact_id"] == elsewhere["contact_id"]


# -- consent evidence -------------------------------------------------------

def test_an_import_asserting_consent_without_evidence_is_refused_entirely():
    account = Account()

    with pytest.raises(ConsentEvidenceRequired):
        account.stage([
            row("Ana Pérez", "+34600111222"),
            row("Bruno Díaz", "+34600111333",
                consent={"purposes": ["marketing"]}),
        ])

    # Nothing staged, not even the good row. A partially staged import is
    # worse than a refused one: the part that made it in looks reviewed.
    assert account.db.store.rows("contacts.contact_import_batches") == []
    assert account.db.store.rows("contacts.contact_import_rows") == []


def test_a_pre_ticked_box_is_not_evidence_and_is_refused_the_same_way():
    account = Account()

    with pytest.raises(ConsentEvidenceRequired):
        account.stage([
            row("Ana Pérez", "+34600111222",
                consent=claim(default_unchecked=False)),
        ])


def test_a_consent_claim_naming_no_purpose_is_refused():
    account = Account()

    with pytest.raises(ImportRowInvalid):
        account.stage([
            row("Ana Pérez", "+34600111222", consent=claim(purposes=())),
        ])


def test_a_row_with_no_consent_still_becomes_a_person_who_cannot_be_reached():
    account = Account()

    batch = account.stage([row("Ana Pérez", "+34600111222")])
    account.importer.apply(TENANT, batch["batch_id"], MANAGER)

    contact = account.contacts_named()[0]
    address = account.address_of(contact["contact_id"])
    decision = account.eligibility(address["address_id"])

    # The person exists -- that is what an import without consent means -- and
    # the destination is unusable for any effect until a human activates it.
    assert contact["display_name"] == "Ana Pérez"
    assert not decision.eligible
    assert decision.reason == "address_not_usable"
    assert account.consent.usability_state(
        TENANT, address["address_id"],
    )["state"] == "proposed"


def test_an_unevidenced_imported_address_waits_in_the_review_queue():
    account = Account()

    batch = account.stage([row("Ana Pérez", "+34600111222")])
    account.importer.apply(TENANT, batch["batch_id"], MANAGER)

    pending = account.importer.queue.pending(TENANT, MANAGER.principal_id)

    assert [entry["display_name"] for entry in pending] == ["Ana Pérez"]
    assert pending[0]["proposed_by_actor_kind"] == "human"


def test_a_row_arriving_with_evidence_is_reachable_after_the_batch_decision():
    account = Account()

    batch = account.stage([
        row("Ana Pérez", "+34600111222", consent=claim()),
    ])
    account.importer.apply(TENANT, batch["batch_id"], MANAGER)

    contact = account.contacts_named()[0]
    address = account.address_of(contact["contact_id"])

    assert account.eligibility(address["address_id"]).eligible
    # And only for the purpose the file evidenced. A grant for marketing is
    # not a grant for anything else.
    assert not account.eligibility(
        address["address_id"], purpose="service",
    ).eligible


def test_the_grant_an_import_writes_keeps_the_evidence_that_defends_it():
    account = Account()

    batch = account.stage([
        row("Ana Pérez", "+34600111222", consent=claim()),
    ])
    account.importer.apply(TENANT, batch["batch_id"], MANAGER)

    contact = account.contacts_named()[0]
    address = account.address_of(contact["contact_id"])
    reading = account.consent.consent_state(
        TENANT, address["address_id"], "sms", "marketing", now=NOW,
    )

    assert reading["state"] == "granted"
    assert reading["jurisdiction"] == "ES"
    assert reading["capture_method"] == "import_form"
    assert reading["default_unchecked"] is True
    assert reading["disclosure_hash"] == ConsentEvidence(
        **evidence()
    ).disclosure_hash
    assert reading["decided_by_principal_id"] == MANAGER.principal_id


# -- authority --------------------------------------------------------------

def test_an_import_into_a_branch_the_importer_cannot_edit_is_refused():
    account = Account()
    account.permissions.restrict(
        TENANT, account.finance, MANAGER.principal_id, DIMENSION_EDIT, ADMIN,
    )

    with pytest.raises(PermissionDenied):
        account.stage([row("Ana Pérez", "+34600111222")],
                      branch=account.finance)

    assert account.db.store.rows("contacts.contact_import_rows") == []


def test_an_import_into_a_branch_of_another_account_is_refused_the_same_way():
    store = FakeStore()
    acme = Account(store, TENANT)
    globex = Account(store, OTHER_TENANT)

    # Same shape of refusal as a branch that does not exist: the manager
    # learns nothing about whether globex has a sales department.
    with pytest.raises(PermissionDenied):
        acme.stage([row("Ana Pérez", "+34600111222")], branch=globex.sales)


def test_an_agent_cannot_apply_a_batch_however_authorized_it_looks():
    account = Account()
    batch = account.stage([row("Ana Pérez", "+34600111222")])

    with pytest.raises(HumanDecisionRequired):
        account.importer.apply(TENANT, batch["batch_id"], ROBOT)

    assert account.contacts_named() == []


def test_the_batch_decision_records_the_human_who_took_it():
    account = Account()
    batch = account.stage([
        row("Ana Pérez", "+34600111222"),
        row("Bruno Díaz", "+34600111333"),
    ])

    summary = account.importer.apply(
        TENANT, batch["batch_id"], MANAGER, reason="alta de feria",
    )
    decided = account.importer.batch(TENANT, batch["batch_id"])

    # One act, many rows -- but never an anonymous one. A bulk mistake is only
    # recoverable if somebody can be asked what they thought they approved.
    assert summary["decided_by_principal_id"] == MANAGER.principal_id
    assert decided["decided_by_actor_kind"] == "human"
    assert decided["decided_at"] == NOW
    assert decided["reason"] == "alta de feria"
    for staged in account.importer.staged_rows(TENANT, batch["batch_id"]):
        assert staged["decided_by_principal_id"] == MANAGER.principal_id
        assert staged["decided_by_actor_kind"] == "human"


def test_applying_a_batch_twice_is_refused_rather_than_doubling_it():
    account = Account()
    batch = account.stage([row("Ana Pérez", "+34600111222")])
    account.importer.apply(TENANT, batch["batch_id"], MANAGER)

    with pytest.raises(ImportAlreadyDecided):
        account.importer.apply(TENANT, batch["batch_id"], MANAGER)

    assert len(account.contacts_named()) == 1


def test_an_import_needs_a_tenant_before_it_needs_anything_else():
    account = Account()

    with pytest.raises(TenantScopeRequired):
        account.importer.stage(None, MANAGER, account.sales, [])
    with pytest.raises(TenantScopeRequired):
        account.importer.apply(None, "import:whatever", MANAGER)
    with pytest.raises(TenantScopeRequired):
        account.directory.record(None, MANAGER.principal_id, "contact:x")


# -- collisions -------------------------------------------------------------

def test_linking_a_collision_takes_edit_authority_where_that_person_lives():
    account = Account()
    elsewhere, _ = account.person(account.finance, "Ana Pérez", "+34600111222")
    account.permissions.restrict(
        TENANT, account.finance, MANAGER.principal_id, DIMENSION_EDIT, ADMIN,
    )
    batch = account.stage([row("Ana P.", "+34600111222")])
    account.importer.apply(TENANT, batch["batch_id"], MANAGER)
    staged = account.importer.staged_rows(TENANT, batch["batch_id"])[0]

    # Claiming "that is the same person" is an assertion about a record in a
    # branch this manager cannot edit, so it is not theirs to make.
    with pytest.raises(PermissionDenied):
        account.importer.decide_row(
            TENANT, staged["import_row_id"], MANAGER, "link",
        )

    settled = account.importer.decide_row(
        TENANT, staged["import_row_id"], MANAGER, "reject",
    )
    assert settled["state"] == "rejected"
    assert settled["applied_contact_id"] is None
    assert len(account.contacts_named()) == 1


def test_linking_a_collision_creates_nobody_and_names_the_person_it_matched():
    account = Account()
    elsewhere, _ = account.person(account.finance, "Ana Pérez", "+34600111222")
    batch = account.stage([row("Ana P.", "+34600111222")])
    account.importer.apply(TENANT, batch["batch_id"], MANAGER)
    staged = account.importer.staged_rows(TENANT, batch["batch_id"])[0]

    settled = account.importer.decide_row(
        TENANT, staged["import_row_id"], MANAGER, "link",
    )

    assert settled["state"] == "applied"
    assert settled["applied_contact_id"] == elsewhere["contact_id"]
    assert len(account.contacts_named()) == 1


def test_a_collision_has_only_the_two_answers_and_no_keep_both():
    account = Account()
    account.person(account.finance, "Ana Pérez", "+34600111222")
    batch = account.stage([row("Ana P.", "+34600111222")])
    account.importer.apply(TENANT, batch["batch_id"], MANAGER)
    staged = account.importer.staged_rows(TENANT, batch["batch_id"])[0]

    with pytest.raises(UnsupportedRowDecision):
        account.importer.decide_row(
            TENANT, staged["import_row_id"], MANAGER, "keep_both",
        )


def test_deciding_a_row_twice_is_refused():
    account = Account()
    account.person(account.finance, "Ana Pérez", "+34600111222")
    batch = account.stage([row("Ana P.", "+34600111222")])
    account.importer.apply(TENANT, batch["batch_id"], MANAGER)
    staged = account.importer.staged_rows(TENANT, batch["batch_id"])[0]
    account.importer.decide_row(TENANT, staged["import_row_id"], MANAGER, "reject")

    with pytest.raises(ImportAlreadyDecided):
        account.importer.decide_row(
            TENANT, staged["import_row_id"], MANAGER, "link",
        )


# -- account isolation ------------------------------------------------------

def test_an_import_cannot_dedupe_against_another_accounts_contacts():
    store = FakeStore()
    acme = Account(store, TENANT)
    globex = Account(store, OTHER_TENANT)
    theirs, _ = globex.person(globex.sales, "Ana Pérez", "+34600111222")

    batch = acme.stage([row("Ana Pérez", "+34600111222")])
    acme.importer.apply(TENANT, batch["batch_id"], MANAGER)
    staged = acme.importer.staged_rows(TENANT, batch["batch_id"])[0]

    # Two accounts holding one number is ordinary, and each keeps its own
    # canonical person. A dedupe that reached across would also be a way to
    # ask "is this number known to anybody else", which is the disclosure.
    assert staged["classification"] == "new"
    assert staged["matched_contact_id"] is None
    assert len(acme.contacts_named()) == 1
    assert len(globex.contacts_named()) == 1


def test_staging_rows_are_invisible_across_accounts():
    store = FakeStore()
    acme = Account(store, TENANT)
    globex = Account(store, OTHER_TENANT)
    batch = acme.stage([row("Ana Pérez", "+34600111222")])

    assert globex.importer.batch(OTHER_TENANT, batch["batch_id"]) is None
    assert globex.importer.staged_rows(OTHER_TENANT, batch["batch_id"]) == []
    with pytest.raises(ImportBatchNotFound):
        globex.importer.review(
            OTHER_TENANT, MANAGER.principal_id, batch["batch_id"],
        )
    with pytest.raises(ImportBatchNotFound):
        globex.importer.apply(OTHER_TENANT, batch["batch_id"], MANAGER)


def test_a_staged_row_cannot_be_pointed_at_another_accounts_contact():
    store = FakeStore()
    acme = Account(store, TENANT)
    globex = Account(store, OTHER_TENANT)
    theirs, _ = globex.person(globex.sales, "Ana Pérez", "+34600111222")
    batch = acme.stage([row("Ana Pérez", "+34600111333")])
    staged = acme.importer.staged_rows(TENANT, batch["batch_id"])[0]

    # The tenant travels inside the reference, so this is refused by the
    # store and not by a predicate somebody has to remember to write.
    with acme.db.transaction() as conn:
        acme.db.set_org_context(conn, TENANT)
        with pytest.raises(FakeIntegrityError):
            conn.execute(
                "update contacts.contact_import_rows set "
                "matched_contact_id = %s "
                "where tenant_id = %s and import_row_id = %s "
                "returning import_row_id",
                (theirs["contact_id"], TENANT, staged["import_row_id"]),
            )


# -- the review surface -----------------------------------------------------

def test_a_reviewer_without_view_authority_never_sees_a_written_destination():
    account = Account()
    batch = account.stage([row("Ana Pérez", "+34600111222")])

    review = account.importer.review(
        TENANT, OPERATOR.principal_id, batch["batch_id"],
    )
    payload = repr(review)

    assert review["redacted"] is True
    assert "display_name" not in review["rows"][0]
    assert "written_address" not in review["rows"][0]
    assert "600111222" not in payload
    assert "Ana Pérez" not in payload
    # Still useful: the reviewer can count, classify, and tell two rows apart.
    assert review["rows"][0]["destination"]["visible_tail"] == "1222"
    assert review["rows"][0]["classification"] == "new"


def test_the_review_says_whether_a_collision_is_this_reviewers_to_link():
    account = Account()
    account.person(account.finance, "Ana Pérez", "+34600111222")
    batch = account.stage([row("Ana P.", "+34600111222")])

    open_to_manager = account.importer.review(
        TENANT, MANAGER.principal_id, batch["batch_id"],
    )
    account.permissions.restrict(
        TENANT, account.finance, MANAGER.principal_id, DIMENSION_EDIT, ADMIN,
    )
    closed_to_manager = account.importer.review(
        TENANT, MANAGER.principal_id, batch["batch_id"],
    )

    # The branch that person lives in is frequently one the reviewer cannot
    # see, so the surface has nothing to infer this from and would say yes.
    assert open_to_manager["rows"][0]["may_link"] is True
    assert closed_to_manager["rows"][0]["may_link"] is False


def test_a_reviewer_holding_view_sees_the_name_and_the_written_form():
    account = Account()
    batch = account.stage([row("Ana Pérez", "+34 600 111 222")])

    review = account.importer.review(
        TENANT, MANAGER.principal_id, batch["batch_id"],
    )

    assert review["redacted"] is False
    assert review["rows"][0]["display_name"] == "Ana Pérez"
    assert review["rows"][0]["written_address"] == "+34 600 111 222"


# -- the record view --------------------------------------------------------

def test_the_record_view_shows_every_axis_and_the_evidence_behind_consent():
    account = Account()
    batch = account.stage([
        row("Ana Pérez", "+34600111222", consent=claim()),
    ])
    account.importer.apply(TENANT, batch["batch_id"], MANAGER)
    contact = account.contacts_named()[0]
    address = account.address_of(contact["contact_id"])
    account.consent.suppress(
        TENANT, address["address_id"], "suppressed_by_bounce",
        reason_code="30003", now=NOW,
    )

    record = account.directory.record(
        TENANT, MANAGER.principal_id, contact["contact_id"], now=NOW,
    )
    entry = record["addresses"][0]

    assert record["display_name"] == "Ana Pérez"
    assert record["branch_path"] == "/acme/sales"
    assert entry["usability"] == "active"
    assert entry["suppression"] == "suppressed_by_bounce"
    assert entry["provider_reachability"] == "reachable"
    assert entry["consent"]["marketing"]["state"] == "granted"
    assert entry["consent"]["marketing"]["jurisdiction"] == "ES"
    # Four axes that do not reduce to one verdict: a live grant and a bounce
    # suppression are both true, and both are readable.
    assert entry["exclusions"]["marketing"] == "suppressed_by_bounce"
    assert record["authorized_channels"] == ()


def test_a_principal_without_view_authority_sees_a_masked_record():
    account = Account()
    account.permissions.grant(
        TENANT, account.org, OPERATOR.principal_id, DIMENSION_CAMPAIGN_USE,
        ADMIN,
    )
    contact, address = account.person(account.sales, "Ana Pérez", "+34600111222")

    record = account.directory.record(
        TENANT, OPERATOR.principal_id, contact["contact_id"], now=NOW,
    )
    payload = repr(record)

    assert record["redacted"] is True
    assert "display_name" not in record
    assert "written_address" not in record["addresses"][0]
    assert "600111222" not in payload
    assert "Ana Pérez" not in payload
    # The projection still answers the question campaign-use exists to ask.
    assert record["addresses"][0]["destination"]["visible_tail"] == "1222"
    assert record["addresses"][0]["exclusions"]["marketing"] == \
        "address_not_usable"


def test_a_principal_holding_neither_view_nor_campaign_use_gets_nothing():
    account = Account()
    contact, _ = account.person(account.sales, "Ana Pérez", "+34600111222")

    # Absence, not refusal. A distinguishable refusal confirms she exists.
    assert account.directory.record(
        TENANT, OPERATOR.principal_id, contact["contact_id"],
    ) is None


def test_a_record_in_another_account_is_absent_rather_than_refused():
    store = FakeStore()
    acme = Account(store, TENANT)
    globex = Account(store, OTHER_TENANT)
    theirs, _ = globex.person(globex.sales, "Ana Pérez", "+34600111222")

    assert acme.directory.record(
        TENANT, MANAGER.principal_id, theirs["contact_id"],
    ) is None


# -- manual entry -----------------------------------------------------------

def test_a_manually_created_address_is_unusable_until_it_is_activated():
    account = Account()

    created = account.directory.create_contact(
        TENANT, MANAGER, account.sales, "Ana Pérez",
        channel="sms", address="+34 600 111 222",
    )
    decision = account.eligibility(created["address_id"])

    assert not decision.eligible
    assert decision.reason == "address_not_usable"


def test_a_manual_create_carrying_evidence_is_reachable_immediately():
    account = Account()

    created = account.directory.create_contact(
        TENANT, MANAGER, account.sales, "Ana Pérez",
        channel="sms", address="+34600111222", consent=claim(),
    )

    assert account.eligibility(created["address_id"]).eligible


def test_retrying_a_partial_manual_create_completes_the_existing_contact():
    account = Account()
    contact, stored = account.person(
        account.sales, "Ana Pérez", "+34600111222",
    )

    created = account.directory.create_contact(
        TENANT, MANAGER, account.sales, "Ana Pérez",
        channel="sms", address="+34 600 111 222", consent=claim(),
    )

    assert created == {
        "contact_id": contact["contact_id"],
        "address_id": stored["address_id"],
    }
    assert account.eligibility(stored["address_id"]).eligible
    assert len(account.contacts_named("Ana Pérez")) == 1


def test_a_manual_create_cannot_claim_an_address_owned_by_another_contact():
    account = Account()
    account.person(account.sales, "Ana Pérez", "+34600111222")

    with pytest.raises(ValueError, match="already belongs to another contact"):
        account.directory.create_contact(
            TENANT, MANAGER, account.sales, "Bea Pérez",
            channel="sms", address="+34600111222", consent=claim(),
        )

    assert len(account.contacts_named()) == 1


def test_a_manual_create_asserting_consent_without_evidence_is_refused():
    account = Account()

    with pytest.raises(ConsentEvidenceRequired):
        account.directory.create_contact(
            TENANT, MANAGER, account.sales, "Ana Pérez",
            channel="sms", address="+34600111222",
            consent={"purposes": ["marketing"]},
        )

    assert account.contacts_named() == []


def test_an_agent_cannot_create_a_contact_by_hand():
    account = Account()

    with pytest.raises(HumanDecisionRequired):
        account.directory.create_contact(
            TENANT, ROBOT, account.sales, "Ana Pérez",
        )


def test_creating_a_contact_in_a_branch_without_edit_authority_is_refused():
    account = Account()
    account.permissions.restrict(
        TENANT, account.finance, MANAGER.principal_id, DIMENSION_EDIT, ADMIN,
    )

    with pytest.raises(PermissionDenied):
        account.directory.create_contact(
            TENANT, MANAGER, account.finance, "Ana Pérez",
        )


def test_an_edit_against_a_record_that_has_since_moved_is_refused():
    account = Account()
    contact, _ = account.person(account.sales, "Ana Pérez", "+34600111222")
    record = account.directory.record(
        TENANT, MANAGER.principal_id, contact["contact_id"],
    )
    account.contacts.add_address(
        TENANT, contact["contact_id"], "email", "ana@example.com",
    )

    with pytest.raises(StaleContactRecord):
        account.directory.update_contact(
            TENANT, MANAGER, contact["contact_id"], record["record_version"],
            {"display_name": "Ana Pérez Gómez"},
        )


def test_an_edit_corrects_identity_and_cannot_reach_consent_or_the_branch():
    account = Account()
    contact, _ = account.person(account.sales, "Ana Pérez", "+34600111222")
    record = account.directory.record(
        TENANT, MANAGER.principal_id, contact["contact_id"],
    )

    updated = account.directory.update_contact(
        TENANT, MANAGER, contact["contact_id"], record["record_version"],
        {"display_name": "Ana Pérez Gómez", "job_title": "Compras"},
    )

    assert updated["record_version"] != record["record_version"]
    assert account.contacts.get_contact(
        TENANT, contact["contact_id"],
    )["display_name"] == "Ana Pérez Gómez"
    # An edit path that could reach these would be a second, quieter way to
    # grant something -- each has its own ledger and its own authority gate.
    for forbidden in ("primary_branch_id", "status", "source"):
        with pytest.raises(ValueError):
            account.directory.update_contact(
                TENANT, MANAGER, contact["contact_id"],
                account.directory.record(
                    TENANT, MANAGER.principal_id, contact["contact_id"],
                )["record_version"],
                {forbidden: "anything"},
            )


def test_an_edit_cannot_blank_the_name_the_record_is_found_by():
    account = Account()
    contact, _ = account.person(account.sales, "Ana Pérez", "+34600111222")
    record = account.directory.record(
        TENANT, MANAGER.principal_id, contact["contact_id"],
    )

    with pytest.raises(ValueError):
        account.directory.update_contact(
            TENANT, MANAGER, contact["contact_id"], record["record_version"],
            {"display_name": "   "},
        )


# -- the permission editor --------------------------------------------------

def test_a_principal_cannot_grant_an_authority_it_does_not_itself_hold():
    account = Account()
    branch_admin = Actor.human("principal:branchadmin", [AUTHORITY_ADMINISTER])
    for dimension in (DIMENSION_ADMINISTER, DIMENSION_VIEW):
        account.permissions.grant(
            TENANT, account.sales, branch_admin.principal_id, dimension, ADMIN,
        )

    # Holds administer and view here, so view is delegable.
    account.directory.set_branch_permission(
        TENANT, branch_admin, account.sales, OPERATOR.principal_id,
        DIMENSION_VIEW, "grant",
    )

    # Does not hold campaign-use, so handing it out would be creating
    # privilege rather than delegating it.
    with pytest.raises(PermissionDenied):
        account.directory.set_branch_permission(
            TENANT, branch_admin, account.sales, OPERATOR.principal_id,
            DIMENSION_CAMPAIGN_USE, "grant",
        )

    assert account.permissions.holds(
        TENANT, OPERATOR.principal_id, account.sales, DIMENSION_VIEW,
    )
    assert not account.permissions.holds(
        TENANT, OPERATOR.principal_id, account.sales, DIMENSION_CAMPAIGN_USE,
    )


def test_an_administrator_of_one_branch_cannot_open_another():
    account = Account()
    branch_admin = Actor.human("principal:branchadmin", [AUTHORITY_ADMINISTER])
    for dimension in (DIMENSION_ADMINISTER, DIMENSION_VIEW):
        account.permissions.grant(
            TENANT, account.sales, branch_admin.principal_id, dimension, ADMIN,
        )

    with pytest.raises(PermissionDenied):
        account.directory.set_branch_permission(
            TENANT, branch_admin, account.finance, OPERATOR.principal_id,
            DIMENSION_VIEW, "grant",
        )


def test_closing_a_dimension_does_not_need_the_authority_opening_it_does():
    account = Account()
    branch_admin = Actor.human("principal:branchadmin", [AUTHORITY_ADMINISTER])
    account.permissions.grant(
        TENANT, account.sales, branch_admin.principal_id, DIMENSION_ADMINISTER,
        ADMIN,
    )
    account.permissions.grant(
        TENANT, account.org, OPERATOR.principal_id, DIMENSION_CAMPAIGN_USE,
        ADMIN,
    )

    # Restrictive, so the asymmetry KTD13 sets up applies: an administrator
    # who cannot hand campaign-use out can still take it away here.
    account.directory.set_branch_permission(
        TENANT, branch_admin, account.sales, OPERATOR.principal_id,
        DIMENSION_CAMPAIGN_USE, "restrict",
    )

    assert not account.permissions.holds(
        TENANT, OPERATOR.principal_id, account.sales, DIMENSION_CAMPAIGN_USE,
    )
    assert account.permissions.holds(
        TENANT, OPERATOR.principal_id, account.org, DIMENSION_CAMPAIGN_USE,
    )


def test_the_editor_sends_what_may_be_delegated_rather_than_a_role():
    account = Account()
    branch_admin = Actor.human("principal:branchadmin", [AUTHORITY_ADMINISTER])
    for dimension in (DIMENSION_ADMINISTER, DIMENSION_VIEW, DIMENSION_EDIT):
        account.permissions.grant(
            TENANT, account.sales, branch_admin.principal_id, dimension, ADMIN,
        )

    view = account.directory.branch_permissions(
        TENANT, branch_admin.principal_id, account.iberia,
    )

    assert view["branch_path"] == "/acme/sales/iberia"
    assert set(view["grantable"]) == {
        DIMENSION_ADMINISTER, DIMENSION_VIEW, DIMENSION_EDIT,
    }
    assert DIMENSION_CAMPAIGN_USE not in view["grantable"]
    # Inherited from /acme/sales, and nothing is written at this branch yet.
    assert view["decisions"] == ()


def test_the_permission_editor_is_closed_to_a_principal_who_cannot_administer():
    account = Account()

    assert account.directory.branch_permissions(
        TENANT, MANAGER.principal_id, account.sales,
    ) is None


def test_an_agent_cannot_change_a_permission():
    account = Account()

    with pytest.raises(HumanDecisionRequired):
        account.directory.set_branch_permission(
            TENANT, ROBOT, account.sales, OPERATOR.principal_id,
            DIMENSION_VIEW, "grant",
        )


# -- staging lookups --------------------------------------------------------

def test_an_unknown_batch_or_row_is_named_as_missing_rather_than_returning_empty():
    account = Account()

    assert account.importer.batch(TENANT, "import:nope") is None
    with pytest.raises(ImportBatchNotFound):
        account.importer.review(TENANT, MANAGER.principal_id, "import:nope")
    with pytest.raises(ImportRowNotFound):
        account.importer.decide_row(
            TENANT, "importrow:nope", MANAGER, "reject",
        )
