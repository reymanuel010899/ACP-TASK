"""Repo-wide pytest configuration.

Two cross-cutting fixes needed once real Postgres persistence (U1-U5)
replaced per-process in-memory dicts across the backend:

1. **Connection-pool exhaustion.** ``Database`` is meant to be constructed
   once per service process and reused (see its docstring) — but every
   repository class defaults to constructing its own ``Database()`` when no
   ``db=`` is passed in, and the test suite's fixtures mostly do exactly
   that: a fresh repository (and therefore a fresh connection pool of up to
   ``max_size`` real Postgres connections) per test. ``psycopg_pool.
   ConnectionPool`` does not reliably close its sockets on garbage
   collection, so across a suite of 600+ tests those pools leak real
   server-side connections until Postgres's ``max_connections`` is
   exhausted (observed: "sorry, too many clients already" partway through a
   full run). Fixed by tracking every ``Database`` instance constructed
   during a test and closing its pool when the test ends.

2. **Shared-identity test pollution.** Since U5, ``registry.app`` persists
   Principals/agents/capabilities/API keys to real Postgres tables instead
   of a fresh in-memory dict per test process. Many test suites across the
   repo — not just ``tests/registry/`` — spin up a real registry server and
   register the same literal ``principal_id`` (e.g. ``"user:owner"``,
   ``"ed25519_user_alice"``) expecting a fresh 200/201, not the 409 a second
   run now produces. Rather than duplicate this truncation fixture in every
   directory that happens to touch a registry server (registry, services,
   federation, marketplace, integration, web, agents, e2e — the list kept
   growing), it lives here once, globally, before every test in the suite.
   Directories with their OWN additional persisted state (``tests/vault/``,
   ``tests/audit/``) keep their own narrower fixtures for those schemas.
"""

import os

import pytest

from libs.db import Database

_original_init = Database.__init__
_live_instances = []


def _tracked_init(self, *args, **kwargs):
    _original_init(self, *args, **kwargs)
    _live_instances.append(self)


Database.__init__ = _tracked_init


@pytest.fixture(autouse=True)
def _clean_shared_identity_tables():
    # Schema/spec-only CI jobs do not start Postgres because these tests never
    # exercise persistence. Keep their collection independent from a database.
    if os.environ.get("PYTEST_SKIP_SHARED_DB_CLEANUP") == "1":
        yield
        return

    db = Database()
    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "truncate table identity.principals, catalog.capabilities, "
                "registry.apps, registry.api_keys cascade"
            )
        conn.commit()
    yield


@pytest.fixture(autouse=True)
def _close_database_pools_after_each_test():
    yield
    while _live_instances:
        db = _live_instances.pop()
        try:
            db.close()
        except Exception:
            pass
