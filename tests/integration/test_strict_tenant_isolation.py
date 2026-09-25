"""Real-role CRUD checks for the strict PostgreSQL tenant boundary."""

import os
import uuid

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo


DEFAULT_TEST_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/agenttrust"


@pytest.fixture(scope="module")
def pg_dsn():
    dsn = os.environ.get("DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    try:
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('registry.agent_ownership')")
                if cur.fetchone()[0] is None:
                    pytest.skip(
                        "migration 0029 is not applied; run infra/roles.sql and "
                        "python -m tools.migrate against the test database"
                    )
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip("strict tenant PostgreSQL fixture unavailable: %s" % exc)
    return dsn


def _runtime_dsn(admin_dsn):
    info = conninfo_to_dict(admin_dsn)
    info.update(
        user="marketplace_svc",
        password="marketplace_svc_dev_password",
    )
    return make_conninfo(**info)


def _set_org(cur, organization_id):
    cur.execute(
        "SELECT set_config('app.current_org_id', %s, true)",
        (organization_id,),
    )


def test_runtime_role_cannot_bypass_rls_or_own_the_table(pg_dsn):
    with psycopg.connect(pg_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT rolsuper, rolbypassrls FROM pg_roles "
                "WHERE rolname = 'marketplace_svc'"
            )
            assert cur.fetchone() == (False, False)
            cur.execute(
                "SELECT tableowner FROM pg_tables "
                "WHERE schemaname = 'marketplace' AND tablename = 'tasks'"
            )
            assert cur.fetchone()[0] != "marketplace_svc"


def test_task_crud_and_reassignment_fail_closed_across_tenants(pg_dsn):
    suffix = uuid.uuid4().hex[:10]
    org_a = "org:strict-a:%s" % suffix
    org_b = "org:strict-b:%s" % suffix
    author = "user:strict:%s" % suffix
    task_a = "task:strict-a:%s" % suffix
    task_b = "task:strict-b:%s" % suffix
    task_quarantine = "task:strict-null:%s" % suffix

    with psycopg.connect(pg_dsn) as admin:
        with admin.cursor() as cur:
            cur.execute(
                "INSERT INTO identity.organizations (organization_id, name) "
                "VALUES (%s, 'Strict A'), (%s, 'Strict B')",
                (org_a, org_b),
            )
            cur.execute(
                "INSERT INTO identity.principals (principal_id, principal_type) "
                "VALUES (%s, 'user')",
                (author,),
            )
            cur.execute(
                "INSERT INTO marketplace.tasks "
                "(task_id, organization_id, author_principal_id, description) "
                "VALUES (%s, %s, %s, 'A'), (%s, %s, %s, 'B'), "
                "(%s, NULL, %s, 'quarantined')",
                (
                    task_a, org_a, author,
                    task_b, org_b, author,
                    task_quarantine, author,
                ),
            )

    runtime_dsn = _runtime_dsn(pg_dsn)
    try:
        # Missing context sees no tenant-owned or quarantined row.
        with psycopg.connect(runtime_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT task_id FROM marketplace.tasks "
                    "WHERE task_id = ANY(%s)",
                    ([task_a, task_b, task_quarantine],),
                )
                assert cur.fetchall() == []

        # Tenant A sees and updates only A; B and quarantine are indistinguishable.
        with psycopg.connect(runtime_dsn) as conn:
            with conn.cursor() as cur:
                _set_org(cur, org_a)
                cur.execute(
                    "SELECT task_id FROM marketplace.tasks "
                    "WHERE task_id = ANY(%s)",
                    ([task_a, task_b, task_quarantine],),
                )
                assert {row[0] for row in cur.fetchall()} == {task_a}
                cur.execute(
                    "UPDATE marketplace.tasks SET description = 'updated' "
                    "WHERE task_id = %s",
                    (task_a,),
                )
                assert cur.rowcount == 1
                cur.execute(
                    "UPDATE marketplace.tasks SET description = 'stolen' "
                    "WHERE task_id = %s",
                    (task_b,),
                )
                assert cur.rowcount == 0
                cur.execute(
                    "DELETE FROM marketplace.tasks WHERE task_id = %s",
                    (task_b,),
                )
                assert cur.rowcount == 0

        # INSERT and tenant-key reassignment are protected by WITH CHECK.
        with psycopg.connect(runtime_dsn) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with conn.cursor() as cur:
                    _set_org(cur, org_a)
                    cur.execute(
                        "INSERT INTO marketplace.tasks "
                        "(task_id, organization_id, author_principal_id, description) "
                        "VALUES (%s, %s, %s, 'wrong tenant')",
                        ("task:wrong:%s" % suffix, org_b, author),
                    )

        with psycopg.connect(runtime_dsn) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with conn.cursor() as cur:
                    _set_org(cur, org_a)
                    cur.execute(
                        "UPDATE marketplace.tasks SET organization_id = %s "
                        "WHERE task_id = %s",
                        (org_b, task_a),
                    )
    finally:
        with psycopg.connect(pg_dsn) as admin:
            with admin.cursor() as cur:
                cur.execute(
                    "DELETE FROM marketplace.tasks WHERE task_id = ANY(%s)",
                    ([task_a, task_b, task_quarantine, "task:wrong:%s" % suffix],),
                )
                cur.execute(
                    "DELETE FROM identity.principals WHERE principal_id = %s",
                    (author,),
                )
                cur.execute(
                    "DELETE FROM identity.organizations "
                    "WHERE organization_id = ANY(%s)",
                    ([org_a, org_b],),
                )
