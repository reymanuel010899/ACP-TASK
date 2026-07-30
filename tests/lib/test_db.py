"""Tests for the shared DB access layer and migration runner (unit U1).

These tests need a real Postgres (and, for the Redis round-trip scenario, a
real Redis) to run against -- there is nothing meaningful to unit-test in
isolation about "does psycopg talk to a live server" or "does the migration
runner's transaction handling actually roll back". Bring up
``infra/docker-compose.yml`` (or any reachable instance) and point
``DATABASE_URL`` / ``REDIS_URL`` at it before running this file; see the env
var contract documented at the top of ``libs/db.py``.

If neither is reachable, every test in this module is skipped (not failed)
with a message explaining why -- there is no non-DB-dependent subset of
"exercise the DB access layer" to fall back to.

Test scenarios (mirroring the plan's U1 spec):
    * Happy path       -- test_migration_runner_applies_pending_in_order
    * Idempotency      -- test_migration_runner_second_run_is_a_no_op
    * Edge case         -- test_failed_migration_rolls_back_and_is_not_recorded
    * Integration       -- test_database_connection_executes_query_end_to_end
                         -- test_redis_round_trips_a_ttl_key
    * (bonus) org context / roles.sql idempotency, see the last two tests.
"""

import os
import time
import uuid

import psycopg
import pytest

from libs.db import Database
from tools.migrate import run_migrations

try:
    import redis
except ImportError:  # pragma: no cover - exercised only if redis isn't installed
    redis = None

DEFAULT_TEST_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/agenttrust"
DEFAULT_TEST_REDIS_URL = "redis://localhost:6379/0"

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ROLES_SQL_PATH = os.path.join(REPO_ROOT, "infra", "roles.sql")


# ---------------------------------------------------------------------------
# Fixtures: skip (not fail) the whole module if there's nothing to talk to.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_dsn():
    dsn = os.environ.get("DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    try:
        with psycopg.connect(dsn, connect_timeout=3):
            pass
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(
            f"Postgres not reachable at {dsn!r} ({exc}). Bring up "
            f"infra/docker-compose.yml (or point DATABASE_URL at a running "
            f"Postgres 16) to run tests/lib/test_db.py."
        )
    return dsn


@pytest.fixture(scope="module")
def redis_url():
    if redis is None:  # pragma: no cover - environment-dependent
        pytest.skip("redis package not installed (see requirements.txt).")
    url = os.environ.get("REDIS_URL", DEFAULT_TEST_REDIS_URL)
    try:
        client = redis.from_url(url, socket_connect_timeout=3)
        client.ping()
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(
            f"Redis not reachable at {url!r} ({exc}). Bring up "
            f"infra/docker-compose.yml (or point REDIS_URL at a running "
            f"Redis 7) to run tests/lib/test_db.py."
        )
    return url


@pytest.fixture()
def run_id():
    """A short, test-run-unique token so migration filenames and table names
    never collide with a previous (or concurrent) test run against the same
    persistent database -- schema_migrations dedups purely by filename, with
    no notion of "which test wrote this"."""
    return uuid.uuid4().hex[:8]


def _write_migration(migrations_dir, filename, sql):
    path = migrations_dir / filename
    path.write_text(sql)
    return path


def _drop_tables(dsn, table_names):
    if not table_names:
        return
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            for name in table_names:
                cur.execute(f"DROP TABLE IF EXISTS {name}")


def _forget_migrations(dsn, filenames):
    if not filenames:
        return
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM schema_migrations WHERE filename = ANY(%s)",
                (list(filenames),),
            )


# ---------------------------------------------------------------------------
# 1. Happy path -- runner applies pending migrations in filename order.
# ---------------------------------------------------------------------------


def test_migration_runner_applies_pending_in_order(pg_dsn, tmp_path, run_id):
    t1, t2, t3 = f"t_{run_id}_a", f"t_{run_id}_b", f"t_{run_id}_c"
    f1, f2, f3 = f"0001_{run_id}_a.sql", f"0002_{run_id}_b.sql", f"0003_{run_id}_c.sql"

    # 0002 deliberately uses a plain (non-idempotent) CREATE TABLE, not
    # IF NOT EXISTS -- this is what test_migration_runner_second_run_is_a_no_op
    # below relies on to prove idempotency comes from the schema_migrations
    # tracking table, not from the SQL happening to be safe to re-run.
    _write_migration(tmp_path, f1, f"CREATE TABLE IF NOT EXISTS {t1} (id text primary key);")
    _write_migration(tmp_path, f2, f"CREATE TABLE {t2} (id text primary key);")
    _write_migration(tmp_path, f3, f"CREATE TABLE IF NOT EXISTS {t3} (id text primary key);")

    try:
        applied = run_migrations(database_url=pg_dsn, migrations_dir=tmp_path)
        assert applied == [f1, f2, f3]  # filename order preserved

        with psycopg.connect(pg_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT filename FROM schema_migrations WHERE filename = ANY(%s) "
                    "ORDER BY filename",
                    ([f1, f2, f3],),
                )
                assert [row[0] for row in cur.fetchall()] == [f1, f2, f3]

                for table in (t1, t2, t3):
                    cur.execute("SELECT to_regclass(%s)", (table,))
                    assert cur.fetchone()[0] == table, f"{table} should exist"
    finally:
        _drop_tables(pg_dsn, [t1, t2, t3])
        _forget_migrations(pg_dsn, [f1, f2, f3])


# ---------------------------------------------------------------------------
# 2. Idempotency -- running the runner twice applies nothing the second time.
# ---------------------------------------------------------------------------


def test_migration_runner_second_run_is_a_no_op(pg_dsn, tmp_path, run_id):
    t1, t2 = f"t_{run_id}_x", f"t_{run_id}_y"
    f1, f2 = f"0001_{run_id}_x.sql", f"0002_{run_id}_y.sql"

    # f2 is plain CREATE TABLE (no IF NOT EXISTS): if the runner ever
    # re-executed it on a second pass, this statement alone would raise
    # "relation already exists" -- the assertions below confirm it doesn't.
    _write_migration(tmp_path, f1, f"CREATE TABLE IF NOT EXISTS {t1} (id text primary key);")
    _write_migration(tmp_path, f2, f"CREATE TABLE {t2} (id text primary key);")

    try:
        first = run_migrations(database_url=pg_dsn, migrations_dir=tmp_path)
        assert first == [f1, f2]

        with psycopg.connect(pg_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM schema_migrations WHERE filename = ANY(%s)",
                    ([f1, f2],),
                )
                count_after_first = cur.fetchone()[0]

        second = run_migrations(database_url=pg_dsn, migrations_dir=tmp_path)
        assert second == []  # nothing pending -> nothing applied, no error

        with psycopg.connect(pg_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM schema_migrations WHERE filename = ANY(%s)",
                    ([f1, f2],),
                )
                count_after_second = cur.fetchone()[0]

        assert count_after_second == count_after_first == 2
    finally:
        _drop_tables(pg_dsn, [t1, t2])
        _forget_migrations(pg_dsn, [f1, f2])


# ---------------------------------------------------------------------------
# 3. Edge case -- a mid-statement failure rolls back and isn't recorded.
# ---------------------------------------------------------------------------


def test_failed_migration_rolls_back_and_is_not_recorded(pg_dsn, tmp_path, run_id):
    t_good, t_bad = f"t_{run_id}_good", f"t_{run_id}_bad"
    f_good, f_bad = f"0001_{run_id}_good.sql", f"0002_{run_id}_bad.sql"

    _write_migration(
        tmp_path, f_good, f"CREATE TABLE IF NOT EXISTS {t_good} (id text primary key);"
    )
    # f_bad's first statement would succeed on its own; the second
    # references a table that doesn't exist, so the whole file must roll
    # back as one unit -- t_bad must NOT exist afterward.
    _write_migration(
        tmp_path,
        f_bad,
        f"CREATE TABLE {t_bad} (id text primary key);\n"
        f"INSERT INTO nonexistent_table_{run_id} (id) VALUES ('x');\n",
    )

    try:
        with pytest.raises(Exception):
            run_migrations(database_url=pg_dsn, migrations_dir=tmp_path)

        with psycopg.connect(pg_dsn) as conn:
            with conn.cursor() as cur:
                # the earlier, valid file in the same run must still have
                # been applied and recorded -- one file's failure doesn't
                # retroactively undo an earlier file's already-committed work.
                cur.execute("SELECT to_regclass(%s)", (t_good,))
                assert cur.fetchone()[0] == t_good

                cur.execute("SELECT filename FROM schema_migrations WHERE filename = %s", (f_good,))
                assert cur.fetchone() is not None

                # the failing file's own work must be fully rolled back.
                cur.execute("SELECT to_regclass(%s)", (t_bad,))
                assert cur.fetchone()[0] is None

                cur.execute("SELECT filename FROM schema_migrations WHERE filename = %s", (f_bad,))
                assert cur.fetchone() is None
    finally:
        _drop_tables(pg_dsn, [t_good, t_bad])
        _forget_migrations(pg_dsn, [f_good, f_bad])


# ---------------------------------------------------------------------------
# 4. Integration -- libs/db.py against a real Postgres; redis round trip.
# ---------------------------------------------------------------------------


def test_database_connection_executes_query_end_to_end(pg_dsn):
    db = Database(dsn=pg_dsn)
    try:
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                assert cur.fetchone() == (1,)
    finally:
        db.close()


def test_redis_round_trips_a_ttl_key(redis_url):
    client = redis.from_url(redis_url)
    key = f"agenttrust:test:{uuid.uuid4().hex}"
    try:
        client.set(key, "value", px=200)  # 200ms TTL
        assert client.get(key) == b"value"
        time.sleep(0.5)
        assert client.get(key) is None  # expired
    finally:
        client.delete(key)


# ---------------------------------------------------------------------------
# Bonus coverage: libs/db.py's transaction()/set_org_context() helper, and
# infra/roles.sql applying cleanly (and idempotently) with zero schemas
# present -- not explicitly required by the U1 test-scenario list, but cheap
# insurance for the two pieces the "Approach" section calls out by name.
# ---------------------------------------------------------------------------


def test_transaction_commits_and_org_context_is_transaction_scoped(pg_dsn, run_id):
    db = Database(dsn=pg_dsn)
    table = f"t_{run_id}_txn"
    try:
        with db.transaction() as conn:
            db.set_org_context(conn, "org-42")
            with conn.cursor() as cur:
                cur.execute("SELECT current_setting('app.current_org_id', true)")
                assert cur.fetchone()[0] == "org-42"
                cur.execute(f"CREATE TABLE {table} (id text primary key)")
        # transaction() committed on clean exit: the table is visible from a
        # brand new connection.
        with psycopg.connect(pg_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass(%s)", (table,))
                assert cur.fetchone()[0] == table

                # SET LOCAL (via set_config(..., true)) does not leak past
                # the transaction that set it -- a fresh connection/session
                # has never defined the GUC at all (NULL), not merely reset
                # it to empty.
                cur.execute("SELECT current_setting('app.current_org_id', true)")
                assert cur.fetchone()[0] is None
    finally:
        _drop_tables(pg_dsn, [table])
        db.close()


def test_transaction_rolls_back_on_exception(pg_dsn, run_id):
    db = Database(dsn=pg_dsn)
    table = f"t_{run_id}_txn_rb"
    try:
        with pytest.raises(RuntimeError):
            with db.transaction() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"CREATE TABLE {table} (id text primary key)")
                raise RuntimeError("boom")

        with psycopg.connect(pg_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass(%s)", (table,))
                assert cur.fetchone()[0] is None  # rolled back, never committed
    finally:
        _drop_tables(pg_dsn, [table])
        db.close()


def test_roles_sql_applies_cleanly_and_idempotently_with_no_schemas(pg_dsn):
    with open(ROLES_SQL_PATH) as f:
        roles_sql = f.read()

    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(roles_sql)  # first apply
            cur.execute(roles_sql)  # re-apply: must not error

            cur.execute(
                "SELECT rolname FROM pg_catalog.pg_roles WHERE rolname = ANY(%s) "
                "ORDER BY rolname",
                (["registry_svc", "vault_svc", "audit_svc", "trust_svc", "marketplace_svc"],),
            )
            roles = [row[0] for row in cur.fetchall()]

    assert roles == ["audit_svc", "marketplace_svc", "registry_svc", "trust_svc", "vault_svc"]
