"""The tree, the canonical record, and the moves that could corrupt either."""

import pytest

from libs.contacts_repository import (
    BranchNotFound,
    ContactNotFound,
    ContactsRepository,
    CyclicBranchMove,
    InvalidBranchPlacement,
    TenantScopeRequired,
    normalize_channel_address,
    normalize_path,
    slugify,
)
from tests.contacts.fake_postgres import (
    FakeDatabase,
    FakeIntegrityError,
    FakeStore,
)


TENANT = "org:acme"


def _repository(store=None):
    db = FakeDatabase(store)
    return ContactsRepository(db), db


def _tree(repository, tenant=TENANT):
    """/acme -> /acme/sales -> /acme/sales/emea, plus a second department."""
    org = repository.create_branch(tenant, "Acme", kind="organization")
    sales = repository.create_branch(
        tenant, "Sales", kind="department", parent_branch_id=org["branch_id"],
    )
    emea = repository.create_branch(
        tenant, "EMEA", kind="folder", parent_branch_id=sales["branch_id"],
    )
    support = repository.create_branch(
        tenant, "Support", kind="department",
        parent_branch_id=org["branch_id"],
    )
    return org, sales, emea, support


# -- the hierarchy ---------------------------------------------------------

def test_a_nested_branch_is_created_and_navigable_by_its_path():
    repository, _db = _repository()
    _org, sales, emea, _support = _tree(repository)

    assert sales["path"] == "/acme/sales"
    assert emea["path"] == "/acme/sales/emea"
    assert emea["depth"] == 2
    assert repository.branch_at_path(TENANT, "/acme/sales/emea") == emea
    # Navigation should not depend on how the caller capitalised or spaced it.
    assert repository.branch_at_path(TENANT, "Acme/Sales/") == sales


def test_folders_nest_freely_and_carry_their_depth():
    repository, _db = _repository()
    _org, _sales, emea, _support = _tree(repository)

    deepest = emea
    for name in ("Spain", "Madrid", "Retail"):
        deepest = repository.create_branch(
            TENANT, name, kind="folder",
            parent_branch_id=deepest["branch_id"],
        )

    assert deepest["path"] == "/acme/sales/emea/spain/madrid/retail"
    assert deepest["depth"] == 5
    assert [branch["slug"] for branch in
            repository.ancestors(TENANT, deepest["branch_id"])] == [
        "acme", "sales", "emea", "spain", "madrid",
    ]


def test_the_tree_shape_is_enforced_rather_than_conventional():
    repository, _db = _repository()
    org, sales, _emea, _support = _tree(repository)

    with pytest.raises(InvalidBranchPlacement):
        repository.create_branch(
            TENANT, "Nested Org", kind="organization",
            parent_branch_id=org["branch_id"],
        )
    with pytest.raises(InvalidBranchPlacement):
        # A department belongs to an organization, not to a department.
        repository.create_branch(
            TENANT, "Inside Sales", kind="department",
            parent_branch_id=sales["branch_id"],
        )
    with pytest.raises(InvalidBranchPlacement):
        repository.create_branch(TENANT, "Loose Folder", kind="folder")


def test_children_lists_the_roots_when_no_branch_is_named():
    repository, _db = _repository()
    org, sales, _emea, support = _tree(repository)

    assert [branch["branch_id"] for branch in repository.children(TENANT)] == [
        org["branch_id"],
    ]
    assert [branch["slug"] for branch in
            repository.children(TENANT, org["branch_id"])] == [
        "sales", "support",
    ]


def test_personal_directory_owner_is_immutable_across_the_tree():
    repository, _db = _repository()
    root = repository.create_branch(
        TENANT, "Contactos", kind="organization",
        owner_principal_id="principal:margo",
    )
    child = repository.create_branch(
        TENANT, "Clientes", kind="folder",
        parent_branch_id=root["branch_id"],
        owner_principal_id="principal:someone-else",
    )

    assert root["owner_principal_id"] == "principal:margo"
    assert child["owner_principal_id"] == "principal:margo"


def test_moving_a_subtree_rewrites_every_path_beneath_it():
    repository, _db = _repository()
    _org, sales, emea, support = _tree(repository)
    spain = repository.create_branch(
        TENANT, "Spain", kind="folder", parent_branch_id=emea["branch_id"],
    )

    moved = repository.move_branch(
        TENANT, emea["branch_id"], support["branch_id"],
    )

    assert moved["path"] == "/acme/support/emea"
    assert repository.branch_at_path(TENANT, "/acme/support/emea/spain")[
        "branch_id"
    ] == spain["branch_id"]
    # The old paths must be gone, or navigation finds two answers.
    assert repository.branch_at_path(TENANT, "/acme/sales/emea") is None
    assert repository.branch_at_path(TENANT, "/acme/sales/emea/spain") is None
    assert repository.children(TENANT, sales["branch_id"]) == []


def test_a_move_that_would_create_cyclic_ancestry_is_rejected():
    repository, _db = _repository()
    _org, _sales, emea, _support = _tree(repository)
    spain = repository.create_branch(
        TENANT, "Spain", kind="folder", parent_branch_id=emea["branch_id"],
    )

    # Under its own child, and under itself. Both would detach the subtree
    # from every root: readable by id, unreachable by path.
    with pytest.raises(CyclicBranchMove):
        repository.move_branch(TENANT, emea["branch_id"], spain["branch_id"])
    with pytest.raises(CyclicBranchMove):
        repository.move_branch(TENANT, emea["branch_id"], emea["branch_id"])

    assert repository.branch_at_path(TENANT, "/acme/sales/emea/spain") is not None


def test_the_store_rejects_a_cycle_even_when_nobody_checked_first():
    """The trigger, not the caller.

    `move_branch` refuses first so the caller gets a named error. This asserts
    the layer underneath, by writing the cyclic parent straight at the store:
    the guard has to survive an import, a backfill, or a future method that
    forgets to look.
    """
    store = FakeStore()
    repository, db = _repository(store)
    _org, _sales, emea, _support = _tree(repository)
    spain = repository.create_branch(
        TENANT, "Spain", kind="folder", parent_branch_id=emea["branch_id"],
    )

    with db.transaction() as conn:
        db.set_org_context(conn, TENANT)
        with pytest.raises(FakeIntegrityError) as caught:
            conn.execute(
                "update contacts.branches set parent_branch_id = %s "
                "where tenant_id = %s and branch_id = %s",
                (spain["branch_id"], TENANT, emea["branch_id"]),
            )

    assert "cyclic" in str(caught.value)


def test_two_siblings_cannot_claim_the_same_path():
    repository, _db = _repository()
    org, _sales, _emea, _support = _tree(repository)

    with pytest.raises(FakeIntegrityError):
        repository.create_branch(
            TENANT, "Sales", kind="department",
            parent_branch_id=org["branch_id"],
        )


def test_a_branch_that_does_not_exist_is_not_found_not_a_crash():
    repository, _db = _repository()
    _tree(repository)

    assert repository.get_branch(TENANT, "branch:nope") is None
    assert repository.branch_at_path(TENANT, "/acme/nope") is None
    with pytest.raises(BranchNotFound):
        repository.ancestors(TENANT, "branch:nope")
    with pytest.raises(BranchNotFound):
        repository.move_branch(TENANT, "branch:nope", None)


# -- the canonical record --------------------------------------------------

def test_a_contact_is_placed_once_and_found_from_its_branch():
    repository, _db = _repository()
    _org, _sales, emea, _support = _tree(repository)

    contact = repository.create_contact(
        TENANT, emea["branch_id"], "Ana Perez",
        given_name="Ana", family_name="Perez",
        locale="es-DO", timezone="America/Santo_Domingo",
        company_name="Acme SRL", job_title="Head of Ops",
    )

    assert contact["primary_branch_id"] == emea["branch_id"]
    assert contact["status"] == "active"
    assert contact["locale"] == "es-DO"
    assert contact["timezone"] == "America/Santo_Domingo"
    assert repository.contacts_in_branch(TENANT, emea["branch_id"]) == [contact]
    assert repository.get_contact(TENANT, contact["contact_id"]) == contact


def test_a_contact_carries_what_a_send_decision_has_to_read():
    repository, _db = _repository()
    _org, _sales, emea, _support = _tree(repository)

    contact = repository.create_contact(
        TENANT, emea["branch_id"], "Ana Perez", external_reference="crm-9",
        source="hubspot",
    )

    # Unknown language and unknown hour are recorded as unknown, not guessed.
    # A template picker must be able to tell "es-DO" from "we do not know".
    assert contact["locale"] is None
    assert contact["timezone"] is None
    assert contact["external_reference"] == "crm-9"
    assert contact["source"] == "hubspot"
    assert contact["merged_into_contact_id"] is None


def test_a_contact_cannot_be_placed_in_a_branch_that_does_not_exist():
    repository, _db = _repository()
    _tree(repository)

    with pytest.raises(FakeIntegrityError):
        repository.create_contact(TENANT, "branch:nope", "Nowhere Person")


def test_moving_a_contact_replaces_its_one_placement():
    repository, _db = _repository()
    _org, sales, emea, support = _tree(repository)
    contact = repository.create_contact(TENANT, emea["branch_id"], "Ana Perez")

    moved = repository.move_contact(
        TENANT, contact["contact_id"], support["branch_id"],
    )

    assert moved["primary_branch_id"] == support["branch_id"]
    assert repository.contacts_in_branch(TENANT, emea["branch_id"]) == []
    assert repository.contacts_in_branch(TENANT, support["branch_id"]) == [moved]
    assert repository.contacts_in_branch(TENANT, sales["branch_id"]) == []


def test_moving_a_contact_that_is_not_there_is_not_found():
    repository, _db = _repository()
    _org, _sales, emea, _support = _tree(repository)

    with pytest.raises(ContactNotFound):
        repository.move_contact(TENANT, "contact:nope", emea["branch_id"])


def test_a_contact_travels_with_the_branch_it_sits_in():
    repository, _db = _repository()
    _org, _sales, emea, support = _tree(repository)
    contact = repository.create_contact(TENANT, emea["branch_id"], "Ana Perez")

    repository.move_branch(TENANT, emea["branch_id"], support["branch_id"])

    assert repository.branch_at_path(TENANT, "/acme/support/emea")[
        "branch_id"
    ] == emea["branch_id"]
    assert repository.contacts_in_branch(TENANT, emea["branch_id"]) == [contact]


# -- addresses -------------------------------------------------------------

def test_one_person_holds_several_addresses_each_on_its_own_row():
    repository, _db = _repository()
    _org, _sales, emea, _support = _tree(repository)
    contact = repository.create_contact(TENANT, emea["branch_id"], "Ana Perez")

    work = repository.add_address(
        TENANT, contact["contact_id"], "sms", "+1 809 555-0100",
        label="work", is_primary=True,
    )
    personal = repository.add_address(
        TENANT, contact["contact_id"], "sms", "+18095550101", label="personal",
    )
    email = repository.add_address(
        TENANT, contact["contact_id"], "email", "Ana@Example.COM",
    )

    # Separate rows is what lets U6 give the work line a consent state the
    # personal line does not share.
    assert {row["address_id"] for row in
            repository.addresses(TENANT, contact["contact_id"])} == {
        work["address_id"], personal["address_id"], email["address_id"],
    }
    assert work["is_primary"] is True
    assert personal["is_primary"] is False


def test_an_address_keeps_what_was_typed_and_indexes_what_was_meant():
    repository, _db = _repository()
    _org, _sales, emea, _support = _tree(repository)
    contact = repository.create_contact(TENANT, emea["branch_id"], "Ana Perez")

    stored = repository.add_address(
        TENANT, contact["contact_id"], "sms", "+1 (809) 555-0100",
    )

    # The human reviewing a proposed send sees what the account entered.
    assert stored["address"] == "+1 (809) 555-0100"
    assert stored["address_normalized"] == "+18095550100"
    assert repository.contact_by_address(TENANT, "sms", "+1809 555 0100")[
        "contact_id"
    ] == contact["contact_id"]


def test_one_number_resolves_to_one_canonical_person_in_an_account():
    repository, _db = _repository()
    _org, _sales, emea, _support = _tree(repository)
    first = repository.create_contact(TENANT, emea["branch_id"], "Ana Perez")
    second = repository.create_contact(TENANT, emea["branch_id"], "Ana P.")
    repository.add_address(TENANT, first["contact_id"], "sms", "+18095550100")

    # A second record claiming the same number is the duplicate R9 exists to
    # prevent, and the store refuses it rather than leaving two answers to
    # "have we already messaged them".
    with pytest.raises(FakeIntegrityError):
        repository.add_address(
            TENANT, second["contact_id"], "sms", "+1-809-555-0100",
        )


def test_promoting_an_address_steps_the_previous_primary_down():
    repository, _db = _repository()
    _org, _sales, emea, _support = _tree(repository)
    contact = repository.create_contact(TENANT, emea["branch_id"], "Ana Perez")
    first = repository.add_address(
        TENANT, contact["contact_id"], "sms", "+18095550100", is_primary=True,
    )

    repository.add_address(
        TENANT, contact["contact_id"], "sms", "+18095550101", is_primary=True,
    )

    primaries = [
        row for row in repository.addresses(TENANT, contact["contact_id"])
        if row["is_primary"]
    ]
    assert [row["address_normalized"] for row in primaries] == ["+18095550101"]
    assert first["address_id"] not in {row["address_id"] for row in primaries}


def test_an_unusable_address_is_refused_before_it_reaches_a_row():
    repository, _db = _repository()
    _org, _sales, emea, _support = _tree(repository)
    contact = repository.create_contact(TENANT, emea["branch_id"], "Ana Perez")

    with pytest.raises(ValueError):
        repository.add_address(TENANT, contact["contact_id"], "sms", "   ")
    with pytest.raises(ValueError):
        repository.add_address(
            TENANT, contact["contact_id"], "carrier-pigeon", "+18095550100",
        )


def test_an_unknown_number_resolves_to_nobody():
    repository, _db = _repository()
    _tree(repository)

    assert repository.contact_by_address(TENANT, "sms", "+18095559999") is None
    assert repository.contact_by_address(TENANT, "sms", "") is None


# -- search ----------------------------------------------------------------

def test_search_finds_by_partial_name_across_the_whole_account():
    repository, _db = _repository()
    _org, sales, emea, support = _tree(repository)
    repository.create_contact(TENANT, emea["branch_id"], "Ana Perez")
    repository.create_contact(TENANT, support["branch_id"], "Anabel Cruz")
    repository.create_contact(TENANT, sales["branch_id"], "Bruno Diaz")

    assert [row["display_name"] for row in
            repository.search_contacts(TENANT, "ana")] == [
        "Ana Perez", "Anabel Cruz",
    ]


def test_search_bounded_to_a_branch_covers_its_whole_subtree():
    repository, _db = _repository()
    _org, sales, emea, support = _tree(repository)
    repository.create_contact(TENANT, emea["branch_id"], "Ana Perez")
    repository.create_contact(TENANT, support["branch_id"], "Anabel Cruz")

    found = repository.search_contacts(
        TENANT, "ana", branch_ids=[sales["branch_id"]],
    )

    # EMEA is under Sales, so authorising Sales authorises what is below it.
    assert [row["display_name"] for row in found] == ["Ana Perez"]


def test_a_branch_scope_naming_nothing_real_returns_nothing():
    repository, _db = _repository()
    _org, _sales, emea, _support = _tree(repository)
    repository.create_contact(TENANT, emea["branch_id"], "Ana Perez")

    assert repository.search_contacts(
        TENANT, "ana", branch_ids=["branch:nope"],
    ) == []
    # An empty authorised set is not "no filter".
    assert repository.search_contacts(TENANT, "ana", branch_ids=[]) == []


# -- the tenant argument itself -------------------------------------------

def test_every_entry_point_refuses_to_run_without_a_tenant():
    repository, _db = _repository()

    for call in (
        lambda: repository.create_branch(None, "Acme", kind="organization"),
        lambda: repository.get_branch(None, "branch:1"),
        lambda: repository.branch_at_path("", "/acme"),
        lambda: repository.children(None),
        lambda: repository.ancestors(None, "branch:1"),
        lambda: repository.subtree(None, "branch:1"),
        lambda: repository.move_branch(None, "branch:1", None),
        lambda: repository.create_contact(None, "branch:1", "Ana"),
        lambda: repository.get_contact(None, "contact:1"),
        lambda: repository.move_contact(None, "contact:1", "branch:1"),
        lambda: repository.contacts_in_branch(None, "branch:1"),
        lambda: repository.search_contacts(None, "ana"),
        lambda: repository.add_address(None, "contact:1", "sms", "+1809"),
        lambda: repository.addresses(None, "contact:1"),
        lambda: repository.contact_by_address(None, "sms", "+1809"),
    ):
        with pytest.raises(TenantScopeRequired):
            call()


def test_the_org_context_is_bound_from_the_same_value_as_the_predicate():
    repository, db = _repository()
    _tree(repository)

    bindings = [
        params[0] for statement, params in db.statements()
        if statement.startswith("select set_config")
    ]

    assert bindings and set(bindings) == {TENANT}


# -- helpers ---------------------------------------------------------------

def test_slugs_and_paths_normalize_the_same_way():
    assert slugify("  Sales & Marketing  ") == "sales-marketing"
    assert slugify("///") == "branch"
    assert normalize_path("Acme/Sales/") == "/acme/sales"
    assert normalize_path("") == "/"


def test_only_telephony_addresses_are_stripped_to_digits():
    assert normalize_channel_address("sms", "+1 (809) 555-0100") == "+18095550100"
    assert normalize_channel_address("voice", "809.555.0100") == "8095550100"
    assert normalize_channel_address("email", " Ana@Example.COM ") == "ana@example.com"
