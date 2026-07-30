"""Shared fixtures for the Vault test suite.

Since U3, ``vault/app.py`` persists to a real Postgres ``vault`` schema
instead of per-process in-memory dicts. That means the suite is no longer
automatically isolated between runs: ``vault.credentials`` is insert-only, so
tests asserting an exact row count for a fixed literal ``principal_id`` (e.g.
``"ed25519_frank"``) accumulate duplicate rows and fail on a second run
against the same long-lived database. This autouse fixture truncates the
vault-owned tables before every test so each test starts from a clean slate,
matching the isolation the old in-memory dicts gave for free.

Scoped to ``vault.*`` only (not ``identity.principals``, which
``VaultRepository._ensure_principal`` also writes to) — other schemas'
tests may rely on identity rows persisting within the same pytest session.
"""

import pytest

from libs.db import Database


@pytest.fixture(autouse=True)
def _clean_vault_tables():
    db = Database()
    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "truncate table vault.credential_grants, "
                "vault.credentials, vault.keyrings cascade"
            )
        conn.commit()
    yield
