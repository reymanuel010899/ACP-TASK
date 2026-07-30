"""Shared Postgres-backed storage for reputation (unit U5, ``trust`` schema --
``migrations/0006_trust.sql``).

This is the ONE code path both Registry (``registry/user_index.py``) and
Verification Service (``services/verification/reputation_store.py``) write
reputation through (R2). Before this unit each kept its own independent,
in-memory ``(principal_id, capability_id) -> {tasks_verified,
tasks_rejected}`` copy with nothing keeping them in sync. Both now call the
methods below against the SAME ``trust.reputation_records`` /
``trust.reputation_portfolio`` tables, so a verdict recorded by either
service is visible to the other on its very next read -- no manual sync
step, no shared Python object required (a shared ``DATABASE_URL`` is the
only thing tying the two together now).

Concurrency
-----------
:meth:`record_verdict` increments via a single atomic
``INSERT ... ON CONFLICT ... DO UPDATE SET count = count + delta`` statement,
never a read-then-write round trip -- concurrent callers (different threads,
different processes, different services) never race each other the way an
in-process lock only ever protected a single process's own dict.

``verification_rate`` is a Postgres ``GENERATED ALWAYS AS ... STORED``
column (see the migration): this module never computes or writes it itself,
which is exactly what keeps it from drifting from the two counts the way a
hand-maintained field could.

FK wrinkles (same resolution pattern as ``vault/repository.py``'s
``_ensure_principal`` -- see that module's docstring for the precedent this
follows)
--------------------------------------------------------------------------
* ``principal_id`` / ``capability_id`` on every row here are real foreign
  keys into ``identity.principals`` / ``catalog.capabilities``. Neither of
  today's callers register those first -- ``UserIndex.record_reputation``
  and ``ReputationStore.record_verdict`` both accept whatever string shows
  up in a request, and some already-committed tests (e.g.
  ``tests/integration/test_all_3_apps_with_independent_registry.py``) use
  non-dot-namespaced capability ids such as ``"code_review"`` that would
  fail ``libs.capability_repository.CapabilityRepository``'s RFC-0001
  pattern check outright. This module's capability auto-registration
  therefore inserts directly with a raw, unvalidated ``INSERT ... ON
  CONFLICT DO NOTHING`` -- a best-effort FK-satisfying placeholder, not an
  authoritative/validated catalog entry. (The database itself has no CHECK
  constraint on ``capability_id``'s shape -- only
  ``CapabilityRepository.register_capability`` enforces the pattern -- so
  this is a deliberate choice to skip that layer here, not a way around a
  real constraint.)
* ``trust.reputation_portfolio.evidence_id`` is a NOT NULL, UNIQUE foreign
  key into ``trust.evidence``. This unit does not wire the full
  Evidence/VerificationResult submission pipeline into Postgres -- per the
  plan, only the ``_reputation``/``_portfolio`` dicts move off
  ``services/verification/reputation_store.py``; ``_results`` (verification
  results by evidence_id) and ``_revoked`` (the revocation list) stay
  exactly as they were, including their optional JSON-file persistence.
  :meth:`add_portfolio_entry` therefore ensures a MINIMAL placeholder
  ``trust.evidence`` row (idempotent insert-if-missing, using only the
  ``evidence_id``/``capability_id`` it has on hand) so the FK is satisfied
  without this module claiming to record the evidence bundle's real
  content -- that remains a later unit's concern if ever needed.

Uses ``libs.db.Database`` for every connection -- no hand-rolled psycopg
connection handling here (KTD1).
"""

from datetime import datetime
from typing import List, Optional

import psycopg
from psycopg.rows import dict_row

from libs.db import Database
from libs.identity_repository import IdentityRepository


class ReputationRepository(object):
    """Repository for ``trust.reputation_records`` and
    ``trust.reputation_portfolio`` -- the ONE write path for reputation,
    shared by Registry and Verification Service (R2)."""

    def __init__(self, db=None):
        # type: (Optional[Database]) -> None
        self._db = db or Database()
        # Composition, not inheritance: reuses U2's insert/lookup logic for
        # the "ensure principal exists" step, same precedent as
        # vault/repository.py.
        self._identity = IdentityRepository(self._db)

    # -- FK-satisfying helpers (see module docstring) ----------------------

    def _ensure_principal(self, principal_id, principal_type="agent"):
        # type: (str, str) -> None
        """Idempotently make sure ``principal_id`` exists in
        ``identity.principals``. Best-effort typing (default ``"agent"``),
        not an authoritative identity claim -- mirrors
        ``vault/repository.py``'s ``_ensure_principal`` exactly."""
        if not principal_id:
            return
        if self._identity.principal_exists(principal_id):
            return
        try:
            self._identity.register_principal(principal_id, principal_type)
        except ValueError:
            pass  # lost a race with a concurrent ensure/registration -- fine

    def _ensure_capability(self, conn, capability_id):
        # type: (object, str) -> None
        """Idempotently make sure ``capability_id`` exists in
        ``catalog.capabilities`` -- deliberately bypassing
        ``CapabilityRepository``'s RFC-0001 pattern validation (see module
        docstring)."""
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO catalog.capabilities
                    (capability_id, version, description)
                VALUES (%s, '0.0.0-auto',
                        'auto-registered by trust on first use')
                ON CONFLICT (capability_id) DO NOTHING
                """,
                (capability_id,),
            )

    def _ensure_evidence(self, conn, evidence_id, capability_id):
        # type: (object, str, str) -> None
        """Idempotently make sure a MINIMAL ``trust.evidence`` row exists so
        a portfolio entry's foreign key is satisfiable. See module
        docstring: this is a placeholder, not a record of the evidence
        bundle's real content."""
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO trust.evidence
                    (evidence_id, session_id, capability_id, schema_valid,
                     tests_passed, artifact_hashes)
                VALUES (%s, %s, %s, true, true, '{}'::jsonb)
                ON CONFLICT (evidence_id) DO NOTHING
                """,
                (evidence_id, evidence_id, capability_id),
            )

    # -- reputation records -------------------------------------------------

    def record_verdict(self, principal_id, capability_id, verdict):
        # type: (str, str, str) -> dict
        """Fold one verdict into the (principal, capability) reputation
        record; returns the updated record. The ONE write path for
        ``trust.reputation_records`` -- both Registry and Verification
        Service call this (R2)."""
        if verdict not in ("verified", "rejected"):
            raise ValueError("verdict must be 'verified' or 'rejected'")
        self._ensure_principal(principal_id)
        verified_delta = 1 if verdict == "verified" else 0
        rejected_delta = 0 if verdict == "verified" else 1
        with self._db.transaction() as conn:
            self._ensure_capability(conn, capability_id)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO trust.reputation_records
                        (principal_id, capability_id, tasks_verified,
                         tasks_rejected)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (principal_id, capability_id) DO UPDATE SET
                        tasks_verified = trust.reputation_records.tasks_verified
                            + excluded.tasks_verified,
                        tasks_rejected = trust.reputation_records.tasks_rejected
                            + excluded.tasks_rejected,
                        updated_at = now()
                    RETURNING *
                    """,
                    (principal_id, capability_id, verified_delta,
                     rejected_delta),
                )
                return _normalize_record(cur.fetchone())

    def get_reputation(self, principal_id, capability_id=None):
        # type: (str, Optional[str]) -> List[dict]
        """All Reputation Records for a principal, optionally scoped to one
        capability. Empty (never an error) when there's no history."""
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                if capability_id is not None:
                    cur.execute(
                        "SELECT * FROM trust.reputation_records "
                        "WHERE principal_id = %s AND capability_id = %s "
                        "ORDER BY capability_id",
                        (principal_id, capability_id),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM trust.reputation_records "
                        "WHERE principal_id = %s ORDER BY capability_id",
                        (principal_id,),
                    )
                return [_normalize_record(row) for row in cur.fetchall()]

    # -- portfolio (verified-work history per subject principal) --------------

    def add_portfolio_entry(self, principal_id, capability_id, evidence_id,
                            verified_at=None):
        # type: (str, str, str, Optional[str]) -> None
        """Append one VERIFIED result to a subject principal's portfolio.
        Idempotent on ``evidence_id`` (unique): re-adding the same
        evidence_id is a no-op rather than an error."""
        self._ensure_principal(principal_id)
        parsed = _parse_verified_at(verified_at)
        # Note: trust.reputation_portfolio carries the immutability rules
        # (DO INSTEAD NOTHING on UPDATE/DELETE) from migrations/0006_trust.sql,
        # and Postgres does not allow an INSERT ... ON CONFLICT clause on any
        # table that has rules defined on it (regardless of which command the
        # rule targets) -- "FeatureNotSupported: INSERT with an ON CONFLICT
        # clause cannot be used with table that has INSERT or UPDATE rules".
        # Idempotency on the unique evidence_id is therefore handled by
        # catching UniqueViolation instead of ON CONFLICT DO NOTHING.
        with self._db.transaction() as conn:
            self._ensure_capability(conn, capability_id)
            self._ensure_evidence(conn, evidence_id, capability_id)
            try:
                # Nested `with conn.transaction():` creates a SAVEPOINT
                # (psycopg3 nests automatically when already inside a
                # transaction) -- so catching UniqueViolation here only
                # rolls back this one insert, not the ensure_capability/
                # ensure_evidence work already done above in the same outer
                # transaction.
                with conn.transaction():
                    with conn.cursor() as cur:
                        if parsed is not None:
                            cur.execute(
                                """
                                INSERT INTO trust.reputation_portfolio
                                    (subject_principal_id, capability_id,
                                     evidence_id, verified_at)
                                VALUES (%s, %s, %s, %s)
                                """,
                                (principal_id, capability_id, evidence_id,
                                 parsed),
                            )
                        else:
                            cur.execute(
                                """
                                INSERT INTO trust.reputation_portfolio
                                    (subject_principal_id, capability_id,
                                     evidence_id)
                                VALUES (%s, %s, %s)
                                """,
                                (principal_id, capability_id, evidence_id),
                            )
            except psycopg.errors.UniqueViolation:
                pass  # evidence_id already has a portfolio entry -- fine

    def get_portfolio(self, principal_id, capability_id=None, limit=None):
        # type: (str, Optional[str], Optional[int]) -> List[dict]
        """Verified portfolio entries for a subject principal, newest first
        (``verified_at`` DESC, ``seq`` DESC to break same-timestamp ties in
        insertion order -- ``seq`` is never exposed to callers). Empty
        (never an error) for a principal with no verified history."""
        query = (
            "SELECT evidence_id, capability_id, verdict, verified_at "
            "FROM trust.reputation_portfolio WHERE subject_principal_id = %s"
        )
        params = [principal_id]  # type: list
        if capability_id is not None:
            query += " AND capability_id = %s"
            params.append(capability_id)
        query += " ORDER BY verified_at DESC, seq DESC"
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, params)
                return [_normalize_portfolio_entry(row) for row in cur.fetchall()]


def _parse_verified_at(value):
    # type: (object) -> Optional[datetime]
    """Best-effort RFC 3339 parse; ``None`` (let the column default ``now()``
    apply) for anything unparseable rather than raising -- some existing
    tests pass opaque, non-timestamp placeholder strings here directly."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_record(row):
    # type: (Optional[dict]) -> Optional[dict]
    """Map a fetched ``trust.reputation_records`` row to the exact
    ``reputation-record`` schema shape: ``verification_rate`` comes back as
    a ``Decimal`` from Postgres's ``numeric`` column, which jsonschema's
    "number" type check rejects -- cast to ``float``, matching the plain
    float/None the prior in-memory implementation always produced."""
    if row is None:
        return None
    return {
        "principal_id": row["principal_id"],
        "capability_id": row["capability_id"],
        "tasks_verified": row["tasks_verified"],
        "tasks_rejected": row["tasks_rejected"],
        "verification_rate": (
            float(row["verification_rate"])
            if row["verification_rate"] is not None else None
        ),
        "updated_at": (
            row["updated_at"].isoformat()
            if isinstance(row["updated_at"], datetime)
            else row["updated_at"]
        ),
    }


def _normalize_portfolio_entry(row):
    # type: (dict) -> dict
    verified_at = row.get("verified_at")
    return {
        "evidence_id": row["evidence_id"],
        "capability_id": row["capability_id"],
        "verdict": row["verdict"],
        "verified_at": (
            verified_at.isoformat()
            if isinstance(verified_at, datetime) else verified_at
        ),
    }
