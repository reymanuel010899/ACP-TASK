"""End-to-end tests for the strict tenant foundation.

These tests require every migration through 0029 plus ``infra/roles.sql``.
They connect through the real Registry, Marketplace, and Audit runtime roles.
Public Agent Cards remain globally readable; tenant-private ownership, tasks,
and audit entries fail closed. Legacy NULL rows are preserved but invisible.
"""

import os
import uuid

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from apps.marketplace.server.repository import MarketplaceRepository
from audit.repository import AuditRepository
from libs.db import Database, bind_organization_id
from libs.identity_repository import IdentityRepository

DEFAULT_TEST_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/agenttrust"

# infra/roles.sql's dev-only convention: password == "<role>_dev_password".
_SERVICE_ROLE_PASSWORDS = {
    "registry_svc": "registry_svc_dev_password",
    "marketplace_svc": "marketplace_svc_dev_password",
    "audit_svc": "audit_svc_dev_password",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_dsn():
    dsn = os.environ.get("DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    try:
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('registry.agent_ownership')")
                if cur.fetchone() is None:
                    pytest.skip(
                        "migrations/0029_strict_tenant_foundation.sql not applied -- "
                        "run `python -m tools.migrate` against this DATABASE_URL first."
                    )
                cur.execute(
                    "SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'registry_svc'"
                )
                if cur.fetchone() is None:
                    pytest.skip(
                        "infra/roles.sql not applied -- run `psql \"$DATABASE_URL\" "
                        "-f infra/roles.sql` first."
                    )
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(
            f"Postgres not reachable at {dsn!r} ({exc}). Bring up a Postgres 16 "
            f"instance, run infra/roles.sql + `python -m tools.migrate` through "
            f"0029_strict_tenant_foundation.sql, and point DATABASE_URL at it to run "
            f"tests/lib/test_multi_tenancy.py."
        )
    return dsn


@pytest.fixture()
def run_id():
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def admin_db(pg_dsn):
    """A Database wired to the admin/owner DSN -- superuser locally, so it
    bypasses RLS entirely regardless of FORCE. Used ONLY to set up fixture
    rows (including rows with an explicit, real organization_id standing in
    for "some other org"), never to make the actual isolation assertions."""
    database = Database(dsn=pg_dsn)
    yield database
    database.close()


@pytest.fixture(autouse=True)
def _reset_org_context():
    """libs.db's per-thread org-context binding (U9) is process-global state
    on the current thread -- always clear it after every test in this
    module so a test that binds an organization_id never leaks it into a
    later test (in this file or, since pytest runs a module's tests on the
    same thread, any file run afterward in the same session)."""
    yield
    bind_organization_id(None)


def _role_dsn(pg_dsn, role_name):
    info = conninfo_to_dict(pg_dsn)
    info["user"] = role_name
    info["password"] = _SERVICE_ROLE_PASSWORDS[role_name]
    return make_conninfo(**info)


def _cleanup_rows(pg_dsn, principal_ids=(), organization_ids=(), task_ids=(),
                  audit_entry_ids=()):
    with psycopg.connect(pg_dsn) as conn:
        with conn.cursor() as cur:
            if task_ids:
                cur.execute(
                    "DELETE FROM marketplace.tasks WHERE task_id = ANY(%s)",
                    (list(task_ids),),
                )
            if audit_entry_ids:
                cur.execute(
                    "DELETE FROM audit.audit_log WHERE entry_id = ANY(%s)",
                    (list(audit_entry_ids),),
                )
            if principal_ids:
                cur.execute(
                    "DELETE FROM registry.agents WHERE principal_id = ANY(%s)",
                    (list(principal_ids),),
                )
                cur.execute(
                    "DELETE FROM identity.principals WHERE principal_id = ANY(%s)",
                    (list(principal_ids),),
                )
            if organization_ids:
                cur.execute(
                    "DELETE FROM identity.organizations WHERE organization_id = ANY(%s)",
                    (list(organization_ids),),
                )
        conn.commit()


# ---------------------------------------------------------------------------
# 1. Integration -- public Agent Cards, private explicit ownership.
# ---------------------------------------------------------------------------


def test_registry_cards_are_public_but_ownership_is_tenant_private(
    pg_dsn, admin_db, run_id
):
    org_a = f"org_a_{run_id}"
    org_b = f"org_b_{run_id}"
    pid_a = f"agent_a_{run_id}"
    pid_b = f"agent_b_{run_id}"
    pid_solo = f"agent_solo_{run_id}"

    identity = IdentityRepository(admin_db)
    identity.create_organization(org_a, "Org A")
    identity.create_organization(org_b, "Org B")
    identity.register_principal(pid_a, "agent", home_organization_id=org_a)
    identity.register_principal(pid_b, "agent", home_organization_id=org_b)
    identity.register_principal(pid_solo, "agent")  # no home_organization_id

    try:
        with admin_db.connection() as conn:
            with conn.cursor() as cur:
                for pid in (pid_a, pid_b, pid_solo):
                    cur.execute(
                        "INSERT INTO registry.agents (principal_id, agent_card) "
                        "VALUES (%s, '{}'::jsonb)",
                        (pid,),
                    )
                cur.execute(
                    "INSERT INTO registry.agent_ownership "
                    "(principal_id, organization_id) VALUES (%s, %s), (%s, %s)",
                    (pid_a, org_a, pid_b, org_b),
                )

        role_dsn = _role_dsn(pg_dsn, "registry_svc")
        with psycopg.connect(role_dsn, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT set_config('app.current_org_id', %s, true)", (org_a,)
                )
                cur.execute(
                    "SELECT principal_id FROM registry.agents "
                    "WHERE principal_id = ANY(%s)",
                    ([pid_a, pid_b, pid_solo],),
                )
                visible = {row[0] for row in cur.fetchall()}
                cur.execute(
                    "SELECT principal_id FROM registry.agent_ownership "
                    "WHERE principal_id = ANY(%s)",
                    ([pid_a, pid_b, pid_solo],),
                )
                owned = {row[0] for row in cur.fetchall()}

        assert visible == {pid_a, pid_b, pid_solo}
        assert owned == {pid_a}
    finally:
        _cleanup_rows(
            pg_dsn,
            principal_ids=[pid_a, pid_b, pid_solo],
            organization_ids=[org_a, org_b],
        )


# ---------------------------------------------------------------------------
# 2. Integration -- marketplace.tasks, direct-column policy.
# ---------------------------------------------------------------------------


def test_marketplace_tasks_rls_blocks_cross_org_reads(pg_dsn, admin_db, run_id):
    org_a = f"org_a_{run_id}"
    org_b = f"org_b_{run_id}"
    author = f"task_author_{run_id}"

    identity = IdentityRepository(admin_db)
    identity.create_organization(org_a, "Org A")
    identity.create_organization(org_b, "Org B")
    identity.register_principal(author, "user")

    marketplace = MarketplaceRepository(admin_db)
    # admin_db connects as the (locally superuser) owner DSN, which bypasses
    # RLS/WITH CHECK unconditionally -- the only way to hand-craft a row
    # with a real organization_id belonging to "the other org" without
    # first threading app.current_org_id through the insert itself.
    task_a = marketplace.create_task(author, "Org A task", organization_id=org_a)
    task_b = marketplace.create_task(author, "Org B task", organization_id=org_b)
    task_none = marketplace.create_task(author, "Unscoped task")  # organization_id NULL

    try:
        role_dsn = _role_dsn(pg_dsn, "marketplace_svc")
        with psycopg.connect(role_dsn, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT set_config('app.current_org_id', %s, true)", (org_a,)
                )
                cur.execute(
                    "SELECT task_id FROM marketplace.tasks WHERE task_id = ANY(%s)",
                    ([task_a["id"], task_b["id"], task_none["id"]],),
                )
                visible = {row[0] for row in cur.fetchall()}

        assert task_a["id"] in visible
        assert task_b["id"] not in visible, (
            "marketplace_svc scoped to org A must not see org B's task, "
            "even via a hand-crafted query bypassing the app layer's own "
            "filters"
        )
        assert task_none["id"] not in visible, (
            "a quarantined task with no organization must be invisible to "
            "every tenant runtime role"
        )
    finally:
        _cleanup_rows(
            pg_dsn,
            principal_ids=[author],
            organization_ids=[org_a, org_b],
            task_ids=[task_a["id"], task_b["id"], task_none["id"]],
        )


# ---------------------------------------------------------------------------
# 3. Integration -- audit.audit_log, direct-column policy (partitioned).
# ---------------------------------------------------------------------------


def test_audit_log_rls_blocks_cross_org_reads(pg_dsn, admin_db, run_id):
    org_a = f"org_a_{run_id}"
    org_b = f"org_b_{run_id}"
    principal = f"audit_principal_{run_id}"

    identity = IdentityRepository(admin_db)
    identity.create_organization(org_a, "Org A")
    identity.create_organization(org_b, "Org B")
    identity.register_principal(principal, "user")

    audit = AuditRepository(admin_db)
    entry_a = audit.append(
        principal, "permission.check", "allowed", organization_id=org_a
    )
    entry_b = audit.append(
        principal, "permission.check", "allowed", organization_id=org_b
    )
    entry_none = audit.append(principal, "permission.check", "allowed")

    try:
        role_dsn = _role_dsn(pg_dsn, "audit_svc")
        with psycopg.connect(role_dsn, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT set_config('app.current_org_id', %s, true)", (org_a,)
                )
                cur.execute(
                    "SELECT entry_id FROM audit.audit_log WHERE entry_id = ANY(%s)",
                    (
                        [
                            entry_a["entry_id"],
                            entry_b["entry_id"],
                            entry_none["entry_id"],
                        ],
                    ),
                )
                visible = {row[0] for row in cur.fetchall()}

        assert entry_a["entry_id"] in visible
        assert entry_b["entry_id"] not in visible, (
            "audit_svc scoped to org A must not see org B's audit entry, "
            "even via a hand-crafted query bypassing the app layer's own "
            "filters"
        )
        assert entry_none["entry_id"] not in visible, (
            "a quarantined audit entry with no organization must be "
            "invisible to every tenant runtime role"
        )
    finally:
        _cleanup_rows(
            pg_dsn,
            principal_ids=[principal],
            organization_ids=[org_a, org_b],
            audit_entry_ids=[
                entry_a["entry_id"], entry_b["entry_id"], entry_none["entry_id"],
            ],
        )


# ---------------------------------------------------------------------------
# 4. Integration -- libs/db.py's NEW per-thread automatic org-context
#    application (the actual mechanism registry/app.py, vault/app.py,
#    apps/marketplace/server/app.py, audit/app.py and agent_marketplace/
#    app.py's request entrypoints now rely on), not just raw SQL SET LOCAL.
# ---------------------------------------------------------------------------


def test_bind_organization_id_is_applied_automatically_by_database(
    pg_dsn, admin_db, run_id
):
    org_a = f"org_a_{run_id}"
    org_b = f"org_b_{run_id}"
    author = f"task_author2_{run_id}"

    identity = IdentityRepository(admin_db)
    identity.create_organization(org_a, "Org A")
    identity.create_organization(org_b, "Org B")
    identity.register_principal(author, "user")

    marketplace_admin = MarketplaceRepository(admin_db)
    task_a = marketplace_admin.create_task(author, "Org A task", organization_id=org_a)
    task_b = marketplace_admin.create_task(author, "Org B task", organization_id=org_b)

    role_db = Database(dsn=_role_dsn(pg_dsn, "marketplace_svc"))
    try:
        # This is the exact call each service's request entrypoint makes
        # (registry/app.py, vault/app.py, apps/marketplace/server/app.py,
        # audit/app.py, agent_marketplace/app.py's `_bind_org_context`) --
        # note there is no `set_org_context(conn, ...)` call anywhere below:
        # Database.connection()/.transaction() apply it automatically.
        bind_organization_id(org_a)
        with role_db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT task_id FROM marketplace.tasks WHERE task_id = ANY(%s)",
                    ([task_a["id"], task_b["id"]],),
                )
                visible = {row[0] for row in cur.fetchall()}

        assert task_a["id"] in visible
        assert task_b["id"] not in visible, (
            "bind_organization_id('org_a') must be applied automatically by "
            "Database.connection() -- no manual set_org_context call was "
            "made in this test"
        )
    finally:
        role_db.close()
        _cleanup_rows(
            pg_dsn,
            principal_ids=[author],
            organization_ids=[org_a, org_b],
            task_ids=[task_a["id"], task_b["id"]],
        )


# ---------------------------------------------------------------------------
# 5. Integration -- FORCE ROW LEVEL SECURITY binds the table-owning role
#    too, not just ordinary callers (mirrors tests/lib/
#    test_identity_repository.py's precedent exactly, applied to
#    marketplace.tasks as the representative direct-column table).
# ---------------------------------------------------------------------------


def test_force_row_level_security_binds_owner_role_on_tasks(pg_dsn, admin_db, run_id):
    org_a = f"org_a_{run_id}"
    org_b = f"org_b_{run_id}"
    author = f"task_author3_{run_id}"
    owner_stand_in_role = f"test_owner_role_{run_id}"
    owner_password = f"{owner_stand_in_role}_pw"
    original_owner = None

    identity = IdentityRepository(admin_db)
    identity.create_organization(org_a, "Org A")
    identity.create_organization(org_b, "Org B")
    identity.register_principal(author, "user")

    marketplace_admin = MarketplaceRepository(admin_db)
    task_a = marketplace_admin.create_task(author, "Org A task", organization_id=org_a)
    task_b = marketplace_admin.create_task(author, "Org B task", organization_id=org_b)

    try:
        with psycopg.connect(pg_dsn, autocommit=True) as owner_admin_conn:
            with owner_admin_conn.cursor() as cur:
                cur.execute(
                    "SELECT tableowner FROM pg_tables "
                    "WHERE schemaname = 'marketplace' AND tablename = 'tasks'"
                )
                original_owner = cur.fetchone()[0]

                cur.execute(f'DROP ROLE IF EXISTS "{owner_stand_in_role}"')
                cur.execute(
                    psycopg.sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD {}"
                    ).format(
                        psycopg.sql.Identifier(owner_stand_in_role),
                        psycopg.sql.Literal(owner_password),
                    )
                )
                cur.execute(
                    f'GRANT USAGE ON SCHEMA marketplace TO "{owner_stand_in_role}"'
                )
                cur.execute(
                    f'ALTER TABLE marketplace.tasks OWNER TO "{owner_stand_in_role}"'
                )

            owner_dsn = _role_dsn(pg_dsn, "marketplace_svc")
            info = conninfo_to_dict(owner_dsn)
            info["user"] = owner_stand_in_role
            info["password"] = owner_password
            owner_dsn = make_conninfo(**info)

            with psycopg.connect(owner_dsn, connect_timeout=3) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT set_config('app.current_org_id', %s, true)",
                        (org_a,),
                    )
                    cur.execute(
                        "SELECT task_id FROM marketplace.tasks "
                        "WHERE task_id = ANY(%s)",
                        ([task_a["id"], task_b["id"]],),
                    )
                    visible = {row[0] for row in cur.fetchall()}

            assert task_a["id"] in visible
            assert task_b["id"] not in visible, (
                "the table-owning role must ALSO be blocked from org B's "
                "task -- this is what FORCE ROW LEVEL SECURITY (as opposed "
                "to plain ENABLE) guarantees"
            )
    finally:
        with psycopg.connect(pg_dsn, autocommit=True) as owner_admin_conn:
            with owner_admin_conn.cursor() as cur:
                if original_owner is not None:
                    cur.execute(
                        f'ALTER TABLE marketplace.tasks OWNER TO "{original_owner}"'
                    )
                cur.execute(
                    "SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = %s",
                    (owner_stand_in_role,),
                )
                if cur.fetchone() is not None:
                    cur.execute(f'DROP OWNED BY "{owner_stand_in_role}"')
                    cur.execute(f'DROP ROLE "{owner_stand_in_role}"')
        _cleanup_rows(
            pg_dsn,
            principal_ids=[author],
            organization_ids=[org_a, org_b],
            task_ids=[task_a["id"], task_b["id"]],
        )
