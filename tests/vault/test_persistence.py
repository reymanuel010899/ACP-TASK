"""Tests for Postgres-backed Vault persistence (unit U3, ``vault`` schema --
migrations/0003_vault.sql, vault/repository.py).

Needs a real Postgres with migrations/0001_identity.sql and
migrations/0003_vault.sql already applied -- there is nothing meaningful to
unit-test in isolation about "does a real table with real foreign keys
behave like the constraints say it should". Bring up a reachable Postgres,
run ``infra/roles.sql`` then ``python -m tools.migrate``, and point
``DATABASE_URL`` at it before running this file (see the env var contract
documented at the top of ``libs/db.py``).

If Postgres isn't reachable, or the ``vault`` schema hasn't been migrated
yet, every test in this module is skipped (not failed) -- mirroring
tests/lib/test_identity_repository.py's convention.

Test scenarios:
    * Happy path   -- test_keyring_credential_and_grant_survive_a_restart
    * Edge case    -- test_owned_credential_lookup_hides_other_users_rows
    * Integration  -- test_keyring_rotation_persists_and_old_wrap_is_gone
    * Regression   -- test_service_over_http_survives_a_simulated_restart
      (drives the actual HTTP contract via VaultClient, across two
      independently-constructed servers pointed at the same database, the
      closest a test gets to "restart the process")
"""

import os
import threading
import uuid

import psycopg
import pytest
import requests

from libs.db import Database
from libs.vault_client import VaultClient
from vault import crypto
from vault.app import make_server
from vault.repository import VaultRepository

DEFAULT_TEST_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/agenttrust"
TEST_ITERATIONS = 1000


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
                    "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'vault'"
                )
                if cur.fetchone() is None:
                    pytest.skip(
                        "vault schema not present -- run `python -m tools.migrate` "
                        "(after infra/roles.sql) against this DATABASE_URL first."
                    )
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(
            f"Postgres not reachable at {dsn!r} ({exc}). Bring up a Postgres 16 "
            f"instance, run infra/roles.sql + `python -m tools.migrate`, and "
            f"point DATABASE_URL at it to run tests/vault/test_persistence.py."
        )
    return dsn


@pytest.fixture()
def run_id():
    """Short, test-run-unique token so principal/credential ids never
    collide with a previous (or concurrent) run against the same
    persistent database -- unlike the pre-existing tests/vault/* suite
    (which gets a fresh in-memory dict per test and so never needed this),
    a real Postgres instance keeps rows around between runs."""
    return uuid.uuid4().hex[:8]


def _new_repository(pg_dsn):
    """A fresh VaultRepository backed by its own Database/connection pool --
    the same shape of object a freshly-started process would construct,
    used here to simulate "the service restarted" without actually killing
    a process."""
    return VaultRepository(Database(dsn=pg_dsn))


def _cleanup(pg_dsn, user_principal_ids=(), agent_principal_ids=(),
            credential_ids=()):
    with psycopg.connect(pg_dsn) as conn:
        with conn.cursor() as cur:
            if credential_ids:
                cur.execute(
                    "DELETE FROM vault.credential_grants WHERE credential_id = ANY(%s)",
                    (list(credential_ids),),
                )
                cur.execute(
                    "DELETE FROM vault.credentials WHERE credential_id = ANY(%s)",
                    (list(credential_ids),),
                )
            if user_principal_ids:
                cur.execute(
                    "DELETE FROM vault.keyrings WHERE user_principal_id = ANY(%s)",
                    (list(user_principal_ids),),
                )
            all_principals = list(user_principal_ids) + list(agent_principal_ids)
            if all_principals:
                cur.execute(
                    "DELETE FROM identity.principal_keys WHERE principal_id = ANY(%s)",
                    (all_principals,),
                )
                cur.execute(
                    "DELETE FROM identity.principals WHERE principal_id = ANY(%s)",
                    (all_principals,),
                )
        conn.commit()


# ---------------------------------------------------------------------------
# 1. Happy path: keyring + credential + grant all survive a "restart"
#    (a fresh repository instance against the same underlying database).
# ---------------------------------------------------------------------------


def test_keyring_credential_and_grant_survive_a_restart(pg_dsn, run_id):
    user = "ed25519_persist_%s" % run_id
    agent = "agent_persist_%s" % run_id
    repo = _new_repository(pg_dsn)
    try:
        blob, dek = crypto.build_keyring_blob(
            "pw", os.urandom(32), iterations=TEST_ITERATIONS
        )
        repo.store_keyring(user, blob)

        ciphertext, nonce = crypto.encrypt_data(b"sk-live-persisted", dek)
        credential = repo.store_credential(
            user, "stripe key", "api_key",
            crypto.b64encode(ciphertext), crypto.b64encode(nonce),
        )
        credential_id = credential["credential_id"]

        grant = repo.add_grant(credential_id, agent, "read", user)
        assert grant["grant_id"]

        # "Restart": throw away this repository/pool, build a brand new one
        # against the same DSN, and confirm everything is still there.
        restarted = _new_repository(pg_dsn)

        fetched_keyring = restarted.get_keyring(user)
        assert fetched_keyring is not None
        assert fetched_keyring["encrypted_dek"] == blob["encrypted_dek"]
        assert fetched_keyring["encrypted_private_key"] == (
            blob["encrypted_private_key"]
        )

        fetched_credential = restarted.get_credential(credential_id)
        assert fetched_credential is not None
        assert fetched_credential["user_principal_id"] == user
        assert fetched_credential["encrypted_data"] == crypto.b64encode(
            ciphertext
        )

        fetched_grant = restarted.get_active_grant(credential_id, agent)
        assert fetched_grant is not None
        assert fetched_grant["grant_id"] == grant["grant_id"]
        assert fetched_grant["scope"] == "read"
    finally:
        _cleanup(
            pg_dsn, user_principal_ids=[user], agent_principal_ids=[agent],
            credential_ids=[credential_id] if "credential_id" in locals() else [],
        )


# ---------------------------------------------------------------------------
# 2. Edge case: a user cannot fetch another user's credential row --
#    enforced in the repository's SQL WHERE clause, not application code.
# ---------------------------------------------------------------------------


def test_owned_credential_lookup_hides_other_users_rows(pg_dsn, run_id):
    owner = "ed25519_owner_%s" % run_id
    intruder = "ed25519_intruder_%s" % run_id
    repo = _new_repository(pg_dsn)
    credential_id = None
    try:
        ciphertext, nonce = crypto.encrypt_data(b"secret", os.urandom(32))
        record = repo.store_credential(
            owner, "personal note", "note",
            crypto.b64encode(ciphertext), crypto.b64encode(nonce),
        )
        credential_id = record["credential_id"]

        # The rightful owner can fetch it via the ownership-scoped lookup.
        assert repo.get_owned_credential(credential_id, owner) is not None

        # A different principal_id gets None -- the row exists (get_credential
        # still finds it), but get_owned_credential refuses to hand it back
        # under the wrong owner.
        assert repo.get_credential(credential_id) is not None
        assert repo.get_owned_credential(credential_id, intruder) is None

        # And the intruder's own credential listing never includes it.
        assert repo.list_credentials(intruder) == []
    finally:
        _cleanup(
            pg_dsn, user_principal_ids=[owner, intruder],
            credential_ids=[credential_id] if credential_id else [],
        )


# ---------------------------------------------------------------------------
# 3. Integration: keyring rotation persists the new wrap and the old one is
#    gone, surviving a fresh repository instance (simulated restart).
# ---------------------------------------------------------------------------


def test_keyring_rotation_persists_and_old_wrap_is_gone(pg_dsn, run_id):
    user = "ed25519_rotate_%s" % run_id
    repo = _new_repository(pg_dsn)
    try:
        old_blob, _old_dek = crypto.build_keyring_blob(
            "old-pw", os.urandom(32), iterations=TEST_ITERATIONS
        )
        repo.store_keyring(user, old_blob)

        new_blob, _new_dek = crypto.build_keyring_blob(
            "new-pw", os.urandom(32), iterations=TEST_ITERATIONS
        )
        rotation_fields = {
            "encrypted_dek": new_blob["encrypted_dek"],
            "salt": new_blob["salt"],
            "nonce": new_blob["nonce"],
            "kdf": new_blob["kdf"],
            "kdf_params": new_blob["kdf_params"],
            "encrypted_private_key": new_blob["encrypted_private_key"],
        }
        updated = repo.rotate_keyring(user, rotation_fields)
        assert updated["encrypted_dek"] == new_blob["encrypted_dek"]

        # Simulated restart: fresh repository/pool, same database.
        restarted = _new_repository(pg_dsn)
        fetched = restarted.get_keyring(user)
        assert fetched is not None
        assert fetched["encrypted_dek"] == new_blob["encrypted_dek"]
        assert fetched["encrypted_private_key"] == (
            new_blob["encrypted_private_key"]
        )
        # The OLD wrapped DEK is gone -- rotation replaces the row in place,
        # it does not keep the superseded wrapping around anywhere.
        assert fetched["encrypted_dek"] != old_blob["encrypted_dek"]
        assert fetched["encrypted_private_key"] != (
            old_blob["encrypted_private_key"]
        )
    finally:
        _cleanup(pg_dsn, user_principal_ids=[user])


# ---------------------------------------------------------------------------
# 4. Regression, over the real HTTP contract: two independently-constructed
#    servers pointed at the same database -- the closest a test gets to
#    "the vault process restarted" -- see the same data.
# ---------------------------------------------------------------------------


def _base_url(server):
    host, port = server.server_address[:2]
    return "http://%s:%d" % (host, port)


def _run_server(pg_dsn):
    server = make_server(port=0, db=Database(dsn=pg_dsn))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_service_over_http_survives_a_simulated_restart(pg_dsn, run_id):
    user = "ed25519_http_restart_%s" % run_id
    agent = "agent_http_restart_%s" % run_id
    server_a, thread_a = _run_server(pg_dsn)
    credential_id = None
    try:
        client_a = VaultClient(_base_url(server_a))
        private_key = os.urandom(32)
        dek, resp = client_a.register_user_keyring(
            "master-pw", user, private_key, iterations=TEST_ITERATIONS
        )
        assert resp["user_principal_id"] == user

        ciphertext, nonce = crypto.encrypt_data(b'{"token": "gh_persisted"}', dek)
        cred = client_a.store_credential(
            user, "github", "api_token", ciphertext, nonce
        )
        credential_id = cred["credential_id"]
        client_a.grant_access(credential_id, agent, scope="read", granted_by=user)
    finally:
        _stop_server(server_a, thread_a)

    # "Restart": a brand new server/service/repository/pool, same DSN.
    server_b, thread_b = _run_server(pg_dsn)
    try:
        client_b = VaultClient(_base_url(server_b))

        blob = client_b.fetch_keyring(user)
        dek2, private_key2 = client_b.unlock_keyring("master-pw", blob)
        assert dek2 == dek
        assert private_key2 == private_key

        listing = client_b.list_credentials(user)
        assert len(listing) == 1
        assert listing[0]["credential_id"] == credential_id

        access = client_b.request_access(credential_id, agent)
        assert access["access_granted"] is True
        assert crypto.decrypt_data(
            crypto.b64decode(access["encrypted_data"]),
            crypto.b64decode(access["nonce"]),
            dek,
        ) == b'{"token": "gh_persisted"}'
    finally:
        _stop_server(server_b, thread_b)
        _cleanup(
            pg_dsn, user_principal_ids=[user], agent_principal_ids=[agent],
            credential_ids=[credential_id] if credential_id else [],
        )
