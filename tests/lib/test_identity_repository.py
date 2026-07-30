"""Tests for libs/identity_repository.py (unit U2, ``identity`` schema).

Needs a real Postgres with migrations/0001_identity.sql (and
migrations/0002_catalog.sql, since 0001 must be applied for 0002's ordering
to make sense -- see migrations/README.md) already applied -- there is
nothing meaningful to unit-test in isolation about "does an INSERT into a
real table with real constraints behave like the constraints say it should".
Bring up a reachable Postgres, run ``infra/roles.sql`` then
``python -m tools.migrate``, and point ``DATABASE_URL`` at it before running
this file (see the env var contract documented at the top of ``libs/db.py``).

If Postgres isn't reachable, or the ``identity`` schema hasn't been migrated
yet, every test in this module is skipped (not failed).

Test scenarios (mirroring the plan's U2 spec):
    * Happy path   -- test_register_and_fetch_principal
    * Happy path   -- test_key_rotation_enforces_single_active_key
    * Edge case    -- test_organization_members_with_different_roles
    * Integration  -- test_rls_isolation_blocks_cross_org_reads_for_nonowner_and_owner
"""

import os
import uuid

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from libs.db import Database
from libs.identity_repository import IdentityRepository

DEFAULT_TEST_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/agenttrust"

_PUBLIC_KEY_A = "A" * 44
_PUBLIC_KEY_B = "B" * 44
_PUBLIC_KEY_C = "C" * 44


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_dsn():
    dsn = os.environ.get("DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    try:
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'identity'"
                )
                if cur.fetchone() is None:
                    pytest.skip(
                        "identity schema not present -- run `python -m tools.migrate` "
                        "(after infra/roles.sql) against this DATABASE_URL first."
                    )
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(
            f"Postgres not reachable at {dsn!r} ({exc}). Bring up a Postgres 16 "
            f"instance, run infra/roles.sql + `python -m tools.migrate`, and "
            f"point DATABASE_URL at it to run tests/lib/test_identity_repository.py."
        )
    return dsn


@pytest.fixture()
def run_id():
    """Short, test-run-unique token so ids never collide with a previous (or
    concurrent) run against the same persistent database."""
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def db(pg_dsn):
    database = Database(dsn=pg_dsn)
    yield database
    database.close()


@pytest.fixture()
def repo(db):
    return IdentityRepository(db)


def _cleanup_identity_rows(pg_dsn, principal_ids=(), organization_ids=(), team_ids=()):
    with psycopg.connect(pg_dsn) as conn:
        with conn.cursor() as cur:
            if team_ids:
                cur.execute(
                    "DELETE FROM identity.team_members WHERE team_id = ANY(%s)",
                    (list(team_ids),),
                )
                cur.execute(
                    "DELETE FROM identity.teams WHERE team_id = ANY(%s)",
                    (list(team_ids),),
                )
            if organization_ids:
                cur.execute(
                    "DELETE FROM identity.organization_members WHERE organization_id = ANY(%s)",
                    (list(organization_ids),),
                )
            if principal_ids:
                cur.execute(
                    "DELETE FROM identity.principal_keys WHERE principal_id = ANY(%s)",
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


# ---------------------------------------------------------------------------
# 1. Happy path -- register a principal, fetch it.
# ---------------------------------------------------------------------------


def test_register_and_fetch_principal(pg_dsn, repo, run_id):
    pid = f"principal_{run_id}"
    try:
        created = repo.register_principal(
            pid, "agent", display_name="Test Agent", created_by=None
        )
        assert created["principal_id"] == pid
        assert created["principal_type"] == "agent"
        assert created["status"] == "active"

        fetched = repo.get_principal(pid)
        assert fetched is not None
        assert fetched["principal_id"] == pid
        assert repo.principal_exists(pid) is True
        assert repo.principal_exists(f"nonexistent_{run_id}") is False

        # duplicate registration is rejected, not silently overwritten
        with pytest.raises(ValueError):
            repo.register_principal(pid, "agent")

        repo.update_last_active(pid)
        refetched = repo.get_principal(pid)
        assert refetched["last_active_at"] is not None
    finally:
        _cleanup_identity_rows(pg_dsn, principal_ids=[pid])


# ---------------------------------------------------------------------------
# 2. Happy path -- key rotation; exactly one active key enforced.
# ---------------------------------------------------------------------------


def test_key_rotation_enforces_single_active_key(pg_dsn, repo, run_id):
    pid = f"principal_keys_{run_id}"
    try:
        repo.register_principal(pid, "agent")

        first_key = repo.register_key(pid, _PUBLIC_KEY_A)
        assert first_key["status"] == "active"

        # Registering a second "active" key for the same principal WITHOUT
        # revoking the first must raise an integrity error -- the unique
        # partial index (principal_keys_one_active) is the enforcement
        # mechanism, not application logic.
        with pytest.raises(psycopg.errors.UniqueViolation):
            repo.register_key(pid, _PUBLIC_KEY_B)

        # rotate_key does the revoke-then-insert atomically instead.
        rotated = repo.rotate_key(pid, _PUBLIC_KEY_C)
        assert rotated["status"] == "active"
        assert rotated["key_id"] != first_key["key_id"]

        active = repo.get_active_key(pid)
        assert active["key_id"] == rotated["key_id"]
        assert active["public_key"] == _PUBLIC_KEY_C

        all_keys = repo.list_keys(pid)
        assert len(all_keys) == 2
        statuses = {k["key_id"]: k["status"] for k in all_keys}
        assert statuses[first_key["key_id"]] == "revoked"
        assert statuses[rotated["key_id"]] == "active"

        # rotating again still enforces exactly one active key afterward.
        rotated_again = repo.rotate_key(pid, "D" * 44)
        active_keys = [k for k in repo.list_keys(pid) if k["status"] == "active"]
        assert len(active_keys) == 1
        assert active_keys[0]["key_id"] == rotated_again["key_id"]
    finally:
        _cleanup_identity_rows(pg_dsn, principal_ids=[pid])


# ---------------------------------------------------------------------------
# 3. Edge case -- organization + members with different roles, list by role.
# ---------------------------------------------------------------------------


def test_organization_members_with_different_roles(pg_dsn, repo, run_id):
    org_id = f"org_{run_id}"
    owner_pid = f"owner_{run_id}"
    admin_pid = f"admin_{run_id}"
    member_pid = f"member_{run_id}"
    try:
        org = repo.create_organization(org_id, "Test Org", plan="pro")
        assert org["organization_id"] == org_id
        assert org["plan"] == "pro"
        assert repo.organization_exists(org_id) is True

        with pytest.raises(ValueError):
            repo.create_organization(org_id, "Duplicate Org")

        for pid in (owner_pid, admin_pid, member_pid):
            repo.register_principal(pid, "user")

        repo.add_member(org_id, owner_pid, role="owner")
        repo.add_member(org_id, admin_pid, role="admin")
        repo.add_member(org_id, member_pid, role="member")

        # adding the same principal twice is rejected
        with pytest.raises(ValueError):
            repo.add_member(org_id, member_pid, role="member")

        all_members = repo.list_members(org_id)
        assert {m["principal_id"] for m in all_members} == {
            owner_pid,
            admin_pid,
            member_pid,
        }

        owners = repo.list_members(org_id, role="owner")
        assert [m["principal_id"] for m in owners] == [owner_pid]

        admins = repo.list_members(org_id, role="admin")
        assert [m["principal_id"] for m in admins] == [admin_pid]

        members_only = repo.list_members(org_id, role="member")
        assert [m["principal_id"] for m in members_only] == [member_pid]

        fetched = repo.get_member(org_id, admin_pid)
        assert fetched["role"] == "admin"

        removed = repo.remove_member(org_id, member_pid)
        assert removed is True
        assert repo.get_member(org_id, member_pid) is None
    finally:
        _cleanup_identity_rows(
            pg_dsn,
            principal_ids=[owner_pid, admin_pid, member_pid],
            organization_ids=[org_id],
        )


# ---------------------------------------------------------------------------
# 3b. Edge case -- teams and team membership.
# ---------------------------------------------------------------------------


def test_teams_and_team_membership(pg_dsn, repo, run_id):
    org_id = f"org_team_{run_id}"
    pid_a = f"team_member_a_{run_id}"
    pid_b = f"team_member_b_{run_id}"
    team_id = None
    try:
        repo.create_organization(org_id, "Team Org")
        repo.register_principal(pid_a, "user")
        repo.register_principal(pid_b, "user")

        team = repo.create_team(org_id, "Platform Team", description="infra folks")
        team_id = team["team_id"]
        assert len(team_id) == 26  # ULID, not UUID4 (KTD4)

        repo.add_team_member(team_id, pid_a)
        repo.add_team_member(team_id, pid_b)

        with pytest.raises(ValueError):
            repo.add_team_member(team_id, pid_a)

        members = repo.list_team_members(team_id)
        assert {m["principal_id"] for m in members} == {pid_a, pid_b}

        fetched_team = repo.get_team(team_id)
        assert fetched_team["organization_id"] == org_id
    finally:
        _cleanup_identity_rows(
            pg_dsn,
            principal_ids=[pid_a, pid_b],
            organization_ids=[org_id],
            team_ids=[team_id] if team_id else [],
        )


# ---------------------------------------------------------------------------
# 4. Integration -- RLS isolation on identity.organization_members.
# ---------------------------------------------------------------------------


def _role_dsn(pg_dsn, role_name, password):
    info = conninfo_to_dict(pg_dsn)
    info["user"] = role_name
    info["password"] = password
    return make_conninfo(**info)


def test_rls_isolation_blocks_cross_org_reads_for_nonowner_and_owner(pg_dsn, repo, run_id):
    """RLS on identity.organization_members must block cross-tenant reads
    for BOTH an ordinary non-owner role and the table-owning role, proving
    FORCE ROW LEVEL SECURITY (not just ENABLE) is in effect.

    infra/roles.sql does not define a dedicated ``identity_svc`` role (only
    registry_svc/vault_svc/audit_svc/trust_svc/marketplace_svc, each with
    read-only grants on `identity`) -- rather than depend on that file having
    already been applied with this exact shape in whatever environment runs
    this test, this test creates its own throwaway, self-contained
    non-owner role, per the plan's own suggested fallback.

    The table's real owner (from tools/migrate.py's admin DSN) is, in this
    project's infra/docker-compose.yml, the `postgres` superuser -- and
    Postgres superusers unconditionally bypass row security regardless of
    FORCE ROW LEVEL SECURITY (this is fundamental Postgres behavior, not a
    bug in this migration). So to actually PROVE FORCE's effect on an
    "owner" role, this test temporarily reassigns the table's ownership to a
    second throwaway, non-superuser role for the duration of the check, then
    restores the original owner in a `finally` block -- this is the only way
    to exercise FORCE ROW LEVEL SECURITY's owner-binding behavior at all
    when the real deployed owner role is a superuser.
    """
    org_a = f"org_a_{run_id}"
    org_b = f"org_b_{run_id}"
    pid_a = f"rls_pid_a_{run_id}"
    pid_b = f"rls_pid_b_{run_id}"
    nonowner_role = f"test_nonowner_role_{run_id}"
    owner_stand_in_role = f"test_owner_role_{run_id}"
    nonowner_password = f"{nonowner_role}_pw"
    owner_password = f"{owner_stand_in_role}_pw"
    original_owner = None

    repo.create_organization(org_a, "Org A")
    repo.create_organization(org_b, "Org B")
    repo.register_principal(pid_a, "user")
    repo.register_principal(pid_b, "user")
    repo.add_member(org_a, pid_a, role="member")
    repo.add_member(org_b, pid_b, role="member")

    try:
        with psycopg.connect(pg_dsn, autocommit=True) as admin_conn:
            with admin_conn.cursor() as cur:
                cur.execute(
                    "SELECT tableowner FROM pg_tables "
                    "WHERE schemaname = 'identity' AND tablename = 'organization_members'"
                )
                original_owner = cur.fetchone()[0]

                for role_name, password in (
                    (nonowner_role, nonowner_password),
                    (owner_stand_in_role, owner_password),
                ):
                    cur.execute(f'DROP ROLE IF EXISTS "{role_name}"')
                    # CREATE ROLE is DDL -- its PASSWORD clause takes a
                    # literal, not a bind parameter. role_name/password here
                    # are test-generated hex tokens (not external input), so
                    # sql.Literal-quoting them (rather than an f-string) is
                    # purely defense in depth, matching infra/roles.sql's own
                    # format(...%L...) literal-quoting convention.
                    cur.execute(
                        psycopg.sql.SQL(
                            "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD {}"
                        ).format(
                            psycopg.sql.Identifier(role_name),
                            psycopg.sql.Literal(password),
                        )
                    )

                cur.execute(f'GRANT USAGE ON SCHEMA identity TO "{nonowner_role}"')
                cur.execute(
                    f'GRANT SELECT ON identity.organization_members TO "{nonowner_role}"'
                )

            # --- (a) ordinary non-owner role: ENABLE ROW LEVEL SECURITY ---
            nonowner_dsn = _role_dsn(pg_dsn, nonowner_role, nonowner_password)
            with psycopg.connect(nonowner_dsn, connect_timeout=3) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT set_config('app.current_org_id', %s, true)",
                        (org_a,),
                    )
                    cur.execute(
                        "SELECT organization_id FROM identity.organization_members "
                        "WHERE organization_id = ANY(%s)",
                        ([org_a, org_b],),
                    )
                    rows = [r[0] for r in cur.fetchall()]
                    assert org_a in rows
                    assert org_b not in rows, (
                        "non-owner role scoped to org A must not see org B's "
                        "organization_members row"
                    )

            # --- (b) table-owning role: FORCE ROW LEVEL SECURITY ---
            with admin_conn.cursor() as cur:
                # Ownership of the table doesn't imply USAGE on the schema
                # it lives in -- that's a separate, schema-level grant.
                cur.execute(f'GRANT USAGE ON SCHEMA identity TO "{owner_stand_in_role}"')
                cur.execute(
                    f'ALTER TABLE identity.organization_members OWNER TO "{owner_stand_in_role}"'
                )

            owner_dsn = _role_dsn(pg_dsn, owner_stand_in_role, owner_password)
            with psycopg.connect(owner_dsn, connect_timeout=3) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT set_config('app.current_org_id', %s, true)",
                        (org_a,),
                    )
                    cur.execute(
                        "SELECT organization_id FROM identity.organization_members "
                        "WHERE organization_id = ANY(%s)",
                        ([org_a, org_b],),
                    )
                    rows = [r[0] for r in cur.fetchall()]
                    assert org_a in rows
                    assert org_b not in rows, (
                        "the table-owning role must ALSO be blocked from "
                        "org B's row -- this is what FORCE ROW LEVEL SECURITY "
                        "(as opposed to plain ENABLE) guarantees"
                    )
    finally:
        with psycopg.connect(pg_dsn, autocommit=True) as admin_conn:
            with admin_conn.cursor() as cur:
                if original_owner is not None:
                    cur.execute(
                        f'ALTER TABLE identity.organization_members OWNER TO "{original_owner}"'
                    )
                for role_name in (nonowner_role, owner_stand_in_role):
                    cur.execute(
                        f"SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = %s",
                        (role_name,),
                    )
                    if cur.fetchone() is not None:
                        cur.execute(f'DROP OWNED BY "{role_name}"')
                        cur.execute(f'DROP ROLE "{role_name}"')
        _cleanup_identity_rows(
            pg_dsn,
            principal_ids=[pid_a, pid_b],
            organization_ids=[org_a, org_b],
        )
