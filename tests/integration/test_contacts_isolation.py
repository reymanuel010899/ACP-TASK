"""Cross-account denial for the contacts directory and everything it feeds.

Every other isolation test in this repository protects work: a workflow run,
a lease, a receipt. These protect people. A missed predicate here hands one
account the names, phone numbers, and employers of another account's
customers, and there is no later gate that would notice.

So the negative path is the primary proof. These tests were written before
the read paths existed, and each one names the specific mechanism it is
leaning on, because "it returned nothing" is only reassuring when you know
what would have had to fail for it to return something.
"""

import logging

import pytest

from libs.contacts_repository import (
    ContactsRepository,
    TenantScopeRequired,
)
from tests.contacts.fake_postgres import (
    FakeDatabase,
    FakeIntegrityError,
    FakeStore,
)


TENANT_A = "org:acme"
TENANT_B = "org:globex"

# Tenant B's bytes. If any of these reach tenant A, in a return value, an
# exception message, or a log line, the directory has leaked.
B_NAME = "Renata Villalobos"
B_PHONE = "+18095550199"
B_COMPANY = "Globex Dominicana"


def _repository(store=None):
    db = FakeDatabase(store)
    return ContactsRepository(db), db


def _seed(repository, tenant, name, phone, company=None):
    org = repository.create_branch(tenant, "Acme", kind="organization")
    sales = repository.create_branch(
        tenant, "Sales", kind="department",
        parent_branch_id=org["branch_id"],
    )
    contact = repository.create_contact(
        tenant, sales["branch_id"], name, company_name=company,
    )
    repository.add_address(
        tenant, contact["contact_id"], "sms", phone, is_primary=True,
    )
    return org, sales, contact


def test_a_tenant_a_session_presenting_a_tenant_b_contact_id_sees_nothing():
    repository, _db = _repository()
    _seed(repository, TENANT_A, "Ana Perez", "+18095550100")
    _, _, foreign = _seed(repository, TENANT_B, B_NAME, B_PHONE, B_COMPANY)

    assert repository.get_contact(TENANT_A, foreign["contact_id"]) is None


def test_the_refusal_is_not_found_shaped_rather_than_forbidden():
    """Forbidden would confirm the row exists, which is half the answer."""
    repository, _db = _repository()
    _seed(repository, TENANT_A, "Ana Perez", "+18095550100")
    _, foreign_branch, foreign = _seed(
        repository, TENANT_B, B_NAME, B_PHONE, B_COMPANY,
    )

    # Absence, not a permission error, on every read path.
    assert repository.get_contact(TENANT_A, foreign["contact_id"]) is None
    assert repository.get_branch(TENANT_A, foreign_branch["branch_id"]) is None
    assert repository.addresses(TENANT_A, foreign["contact_id"]) == []
    assert repository.contact_by_address(TENANT_A, "sms", B_PHONE) is None


def test_no_tenant_b_bytes_reach_tenant_a_in_a_body_or_in_a_log(caplog):
    repository, _db = _repository()
    _seed(repository, TENANT_A, "Ana Perez", "+18095550100")
    _, foreign_branch, foreign = _seed(
        repository, TENANT_B, B_NAME, B_PHONE, B_COMPANY,
    )

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        observed = [
            repr(repository.get_contact(TENANT_A, foreign["contact_id"])),
            repr(repository.contact_by_address(TENANT_A, "sms", B_PHONE)),
            repr(repository.search_contacts(TENANT_A, "Renata")),
            repr(repository.contacts_in_branch(
                TENANT_A, foreign_branch["branch_id"],
            )),
        ]
        try:
            repository.move_contact(
                TENANT_A, foreign["contact_id"], foreign_branch["branch_id"],
            )
        except Exception as exc:  # noqa: BLE001 - the message is under test
            observed.append("%s: %s" % (type(exc).__name__, exc))

    surface = " ".join(observed) + " " + caplog.text
    for secret in (B_NAME, B_PHONE, B_COMPANY):
        assert secret not in surface


def test_a_read_without_a_tenant_fails_instead_of_returning_rows():
    repository, _db = _repository()
    _, _, contact = _seed(repository, TENANT_A, "Ana Perez", "+18095550100")

    # Not "returns everything", not "returns nothing" -- a refusal, so a
    # caller that forgot to thread the tenant through finds out immediately
    # rather than at the point where the rows are already in a response.
    for call in (
        lambda: repository.get_contact(None, contact["contact_id"]),
        lambda: repository.get_branch("", "branch:anything"),
        lambda: repository.contact_by_address(None, "sms", "+18095550100"),
        lambda: repository.search_contacts(None, "Ana"),
        lambda: repository.addresses(None, contact["contact_id"]),
        lambda: repository.branch_at_path(None, "/acme"),
    ):
        with pytest.raises(TenantScopeRequired):
            call()


def test_row_level_security_still_hides_the_rows_when_the_predicate_is_gone():
    """The backstop, tested without the repository's help.

    Every method above carries its own `tenant_id = %s`. This asserts the
    layer underneath: with tenant A's org context bound and no predicate at
    all, tenant B's rows are not in the result set. That is what forced
    row-level security buys, and it is the only reason a single forgotten
    predicate is a bug rather than a breach.
    """
    store = FakeStore()
    repository, db = _repository(store)
    _seed(repository, TENANT_A, "Ana Perez", "+18095550100")
    _seed(repository, TENANT_B, B_NAME, B_PHONE, B_COMPANY)

    with db.connection() as conn:
        db.set_org_context(conn, TENANT_A)
        rows = conn.execute(
            "select contact_id, tenant_id, display_name from contacts.contacts"
        ).fetchall()

    assert rows, "tenant A should still see its own directory"
    assert {row["tenant_id"] for row in rows} == {TENANT_A}
    assert all(row["display_name"] != B_NAME for row in rows)


def test_an_unbound_org_context_sees_no_contacts_at_all():
    store = FakeStore()
    repository, db = _repository(store)
    _seed(repository, TENANT_A, "Ana Perez", "+18095550100")

    with db.connection() as conn:
        # No set_org_context call: a pooled connection that nobody bound.
        rows = conn.execute(
            "select contact_id from contacts.contacts"
        ).fetchall()

    assert rows == []


def test_every_contacts_statement_the_repository_issues_names_a_tenant():
    repository, db = _repository()
    _, sales, contact = _seed(repository, TENANT_A, "Ana Perez", "+18095550100")
    repository.get_contact(TENANT_A, contact["contact_id"])
    repository.contact_by_address(TENANT_A, "sms", "+18095550100")
    repository.search_contacts(TENANT_A, "Ana", branch_ids=[sales["branch_id"]])
    repository.branch_at_path(TENANT_A, "/acme/sales")
    repository.children(TENANT_A, sales["branch_id"])
    repository.ancestors(TENANT_A, sales["branch_id"])
    repository.move_contact(TENANT_A, contact["contact_id"], sales["branch_id"])

    for statement, _params in db.statements():
        if "contacts." not in statement:
            continue
        assert "tenant_id" in statement, statement


def test_a_contact_cannot_be_placed_in_another_accounts_branch():
    store = FakeStore()
    repository, _db = _repository(store)
    _seed(repository, TENANT_A, "Ana Perez", "+18095550100")
    _, foreign_branch, _ = _seed(repository, TENANT_B, B_NAME, B_PHONE)

    # Structural, not a predicate: the foreign key is
    # (primary_branch_id, tenant_id), so this reference does not resolve.
    with pytest.raises(FakeIntegrityError):
        repository.create_contact(
            TENANT_A, foreign_branch["branch_id"], "Smuggled Person",
        )


def test_a_branch_cannot_be_reparented_under_another_accounts_branch():
    store = FakeStore()
    repository, _db = _repository(store)
    _, mine, _ = _seed(repository, TENANT_A, "Ana Perez", "+18095550100")
    _, foreign_branch, _ = _seed(repository, TENANT_B, B_NAME, B_PHONE)

    with pytest.raises(Exception) as caught:
        repository.move_branch(
            TENANT_A, mine["branch_id"], foreign_branch["branch_id"],
        )

    assert B_NAME not in str(caught.value)


def test_two_accounts_holding_one_phone_number_keep_separate_records():
    shared_number = "+18095550100"
    repository, _db = _repository()
    _, _, mine = _seed(repository, TENANT_A, "Ana Perez", shared_number)
    _, _, theirs = _seed(repository, TENANT_B, B_NAME, shared_number)

    assert mine["contact_id"] != theirs["contact_id"]
    resolved_a = repository.contact_by_address(TENANT_A, "sms", shared_number)
    resolved_b = repository.contact_by_address(TENANT_B, "sms", shared_number)
    assert resolved_a["contact_id"] == mine["contact_id"]
    assert resolved_b["contact_id"] == theirs["contact_id"]
    assert resolved_a["display_name"] == "Ana Perez"


def test_search_never_reaches_across_accounts():
    repository, _db = _repository()
    _seed(repository, TENANT_A, "Renata Suarez", "+18095550100")
    _seed(repository, TENANT_B, B_NAME, B_PHONE, B_COMPANY)

    found = repository.search_contacts(TENANT_A, "Renata")

    assert [row["display_name"] for row in found] == ["Renata Suarez"]


def test_a_branch_scoped_search_cannot_be_widened_with_a_foreign_branch_id():
    repository, _db = _repository()
    _, mine, _ = _seed(repository, TENANT_A, "Ana Perez", "+18095550100")
    _, foreign_branch, _ = _seed(repository, TENANT_B, B_NAME, B_PHONE)

    found = repository.search_contacts(
        TENANT_A, "", branch_ids=[mine["branch_id"], foreign_branch["branch_id"]],
    )

    assert [row["display_name"] for row in found] == ["Ana Perez"]


# -- the surfaces the directory feeds -------------------------------------

def _action_repository(tmp_path):
    from agents.orchestrator.action_repository import ActionRepository

    return ActionRepository(str(tmp_path / "actions.db"))


def _proposal(actions, tenant_id, **overrides):
    fields = dict(
        user_principal_id="user:alice",
        agent_principal_id="agent:concierge",
        credential_id="cred:1",
        capability_id="twilio.sms.send",
        payload={"to": "+18095550100", "body": "hola"},
        expires_at=10_000,
        tenant_id=tenant_id,
    )
    fields.update(overrides)
    return actions.create_proposal(**fields)


def test_a_proposal_carries_the_tenant_that_will_pay_for_it(tmp_path):
    actions = _action_repository(tmp_path)

    proposal = _proposal(actions, TENANT_A)

    assert proposal["tenant_id"] == TENANT_A


def test_another_accounts_proposal_is_not_found_rather_than_forbidden(tmp_path):
    actions = _action_repository(tmp_path)
    proposal = _proposal(actions, TENANT_B, payload={"to": B_PHONE, "body": B_NAME})

    assert actions.get(
        proposal["proposal_id"], proposal["version"], tenant_id=TENANT_A
    ) is None
    assert actions.get_by_idempotency_key(
        proposal["idempotency_key"], tenant_id=TENANT_A
    ) is None


def test_another_account_cannot_approve_a_proposal_holding_a_phone_number(tmp_path):
    actions = _action_repository(tmp_path)
    proposal = _proposal(actions, TENANT_B, payload={"to": B_PHONE, "body": B_NAME})

    assert actions.decide(
        proposal["proposal_id"], proposal["version"], "user:alice", True,
        1_000, tenant_id=TENANT_A,
    ) is False
    assert actions.decide(
        proposal["proposal_id"], proposal["version"], "user:alice", True,
        1_000, tenant_id=TENANT_B,
    ) is True


def test_another_account_cannot_consume_the_approval(tmp_path):
    actions = _action_repository(tmp_path)
    proposal = _proposal(actions, TENANT_B, payload={"to": B_PHONE, "body": B_NAME})
    actions.decide(
        proposal["proposal_id"], proposal["version"], "user:alice", True,
        1_000, tenant_id=TENANT_B,
    )
    binding = {
        "proposal_id": proposal["proposal_id"],
        "version": proposal["version"],
        "user_principal_id": "user:alice",
        "agent_principal_id": "agent:concierge",
        "credential_id": "cred:1",
        "capability_id": "twilio.sms.send",
        "payload_hash": proposal["payload_hash"],
        "idempotency_key": proposal["idempotency_key"],
        "tenant_id": TENANT_A,
    }

    assert actions.consume_approval(binding, 1_001) is None

    binding["tenant_id"] = TENANT_B
    assert actions.consume_approval(binding, 1_001) is not None


def test_a_lease_issued_for_one_account_does_not_validate_for_another(tmp_path):
    actions = _action_repository(tmp_path)
    lease = actions.issue_lease(
        "user:alice", "agent:concierge", "task:1", "cred:1",
        ["twilio.sms.send"], 10_000, tenant_id=TENANT_B, now_ts=1_000,
    )
    binding = {
        "user_principal_id": "user:alice",
        "agent_principal_id": "agent:concierge",
        "task_id": "task:1",
        "credential_id": "cred:1",
        "capability_id": "twilio.sms.send",
        "tenant_id": TENANT_A,
    }

    assert actions.validate_lease(lease, binding, 1_001) is False
    assert actions.consume_lease(lease, binding, 1_001) is False

    binding["tenant_id"] = TENANT_B
    assert actions.validate_lease(lease, binding, 1_001) is True


def test_an_unmapped_principal_fails_hard_instead_of_a_default_tenant(monkeypatch):
    """The fallback that made every unmapped principal one shared account.

    `mapping.get(principal_id) or local_tenant` meant a principal nobody had
    mapped -- a rotated id, a new deployment, a typo -- silently acted inside
    `TESSERA_LOCAL_TENANT_ID`. Survivable for conversation state. For a
    directory of other people's personal data it is the leak itself.
    """
    from libs.tenancy import UnmappedPrincipalError
    from services.oauth.app import _configured_tenant_resolver
    from web.concierge import _tenant_resolver

    monkeypatch.setenv("TESSERA_PRINCIPAL_TENANTS_JSON", "{}")
    monkeypatch.setenv("TESSERA_LOCAL_TENANT_ID", TENANT_A)

    for resolver in (_tenant_resolver(), _configured_tenant_resolver()):
        with pytest.raises(UnmappedPrincipalError):
            resolver("user:unmapped")


def test_a_mapped_principal_still_resolves_to_its_own_account(monkeypatch):
    from services.oauth.app import _configured_tenant_resolver
    from web.concierge import _tenant_resolver

    monkeypatch.setenv(
        "TESSERA_PRINCIPAL_TENANTS_JSON", '{"user:alice": "org:acme"}',
    )
    monkeypatch.setenv("TESSERA_LOCAL_TENANT_ID", TENANT_B)

    for resolver in (_tenant_resolver(), _configured_tenant_resolver()):
        assert resolver("user:alice") == TENANT_A
