"""Shared fixtures for the Audit test suite.

Since U4, ``audit/app.py`` persists to a real Postgres ``audit.audit_log``
table instead of a fresh in-memory list per test/process. That means the
suite is no longer automatically isolated between tests the way the old
``AuditStore`` gave for free: filters that assert an exact ``total_matched``
count would otherwise accumulate rows across the whole test session (and
across repeated runs against the same long-lived database). This autouse
fixture truncates ``audit.audit_log`` before every test, mirroring the exact
pattern ``tests/vault/conftest.py`` established for the same reason in U3.

``TRUNCATE`` (not ``DELETE``) is used deliberately: the append-only rules
``migrations/0004_audit.sql`` installs intercept ``DELETE``/``UPDATE``
statements specifically, and would silently no-op a ``DELETE FROM
audit.audit_log`` here too. ``TRUNCATE`` is a distinct SQL command the rules
don't rewrite, and it cascades through every monthly partition
automatically.

This suite also spins up a real ``registry.app`` server and registers
literal, fixed principal_ids against it (e.g. ``"user:carol"``) — the
shared-identity-table truncation that needs lives once, globally, in the
root ``tests/conftest.py`` (see that module's docstring); this fixture only
owns the ``audit``-specific table.
"""

import pytest

from libs.db import Database


@pytest.fixture(autouse=True)
def _clean_audit_log():
    db = Database()
    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("truncate table audit.audit_log cascade")
        conn.commit()
    yield
