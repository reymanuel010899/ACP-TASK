"""Postgres-backed storage for the Agent Marketplace's hiring grants and
ratings (unit U8, ``marketplace`` schema -- ``migrations/0008_hiring.sql``).

Replaces ``agent_marketplace/hiring.py``'s in-memory ``HiringStore`` (a
``grant_id -> dict`` dict plus an ``agent_principal_id -> {user_principal_id
-> rating}`` dict, guarded by one ``threading.RLock``). ``HiringStore``
itself keeps its exact pre-existing method names/signatures and delegates to
this module (composition), so ``agent_marketplace/app.py`` needed no changes
at all (R10) -- only how a grant/rating gets stored changed, not the shape
callers see.

FK-satisfying auto-registration (same pattern as every prior unit)
-------------------------------------------------------------------
``agent_principal_id``/``user_principal_id`` on ``hiring_grants`` and
``ratings``, and ``capability_id`` on ``grant_capabilities``, are foreign
keys -- but no existing agent-marketplace caller has ever had to register a
principal or a capability as a separate step before hiring or rating.
:meth:`_ensure_principal` / :meth:`_ensure_capability` are the identical
idempotent "insert a minimal row if one doesn't already exist" helpers
``vault/repository.py`` and ``apps/marketplace/server/repository.py``
already established (composition over ``libs.identity_repository.
IdentityRepository`` / a direct ``ON CONFLICT DO NOTHING`` insert into
``catalog.capabilities`` -- see those modules' docstrings for the full
precedent this follows, not reinvented here).

The credential_id cross-schema wrinkle
----------------------------------------
``grant_credential_scopes.credential_id`` is a LOGICAL foreign key into
``vault.credentials`` (U3) with no hard Postgres constraint -- per the design
doc, marketplace and vault may become physically separate databases, so this
is the one relationship enforced at the application layer instead (see
``migrations/0008_hiring.sql``'s header). That application-layer check
already exists and is UNCHANGED by this unit: ``agent_marketplace/app.py``'s
``create_hiring_grant`` calls ``VaultClient.grant_access`` for every
credential scope BEFORE ever calling :meth:`HiringRepository.create_grant`
-- a real HTTP call against the Vault that fails loudly (404/other) on an
unknown ``credential_id``, well before this repository would ever try to
store one. This repository itself never re-validates that call; it only
ever persists ``(credential_id, scope)`` pairs a caller already had Vault
accept.

The "expired" wrinkle (query predicate, not a lazily-written value)
----------------------------------------------------------------------
Today's ``HiringStore._view()`` computes "expired" in Python on every read,
from whatever ``expires_at`` string happens to be sitting in the dict --
never writing that transition back. This module keeps that same "closes on
read, no background job" behavior, but the predicate itself now runs INSIDE
Postgres, against Postgres's own ``now()`` (a single authoritative clock,
not this process's), and the raw ``status`` column is genuinely never set to
``'active' -> 'expired'`` by any write path here -- only an explicit
:meth:`revoke_grant` ever changes ``status`` (to ``'revoked'``). See
``_STATUS_CASE_SQL`` below.

Ratings: append-only history + a materialized running average (KTD8)
------------------------------------------------------------------------
:meth:`set_rating` always INSERTS a new ``marketplace.ratings`` row -- it
never overwrites a prior (agent, user) rating the way today's
``HiringStore.set_rating`` does. ``marketplace.rating_summary`` is kept
current by ``migrations/0008_hiring.sql``'s ``AFTER INSERT`` trigger (an O(1)
incremental running-average update), so :meth:`rating_summary` here is a
single indexed point lookup, never a re-scan.

Uses ``libs.db.Database`` for every connection -- no hand-rolled psycopg
connection handling here (KTD1). ``grant_id`` keeps the pre-existing
``uuid.uuid4()`` string format (see ``migrations/0008_hiring.sql``'s header
for why this -- unlike e.g. ``task_id`` in U6 -- is NOT a ULID).
"""

import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from psycopg.rows import dict_row

from libs.db import Database
from libs.identity_repository import IdentityRepository


def parse_expires_at(value):
    # type: (str) -> datetime
    """Parse an ISO-8601 timestamp ('Z' suffix accepted); raise ValueError.

    Naive timestamps are interpreted as UTC. Defined here (rather than in
    ``agent_marketplace.hiring``) so this module -- which needs it to convert
    a caller-supplied ``expires_at`` string into a ``timestamptz`` parameter
    -- has no import cycle back to ``agent_marketplace.hiring``, which in
    turn imports :class:`HiringRepository` from here.
    ``agent_marketplace.hiring`` re-exports this exact function so
    ``from agent_marketplace.hiring import parse_expires_at`` (the
    pre-existing public API ``agent_marketplace/app.py`` already imports)
    keeps working unchanged.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("expires_at must be a non-empty string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed

#: Computes the CALLER-VISIBLE status of a hiring_grants row without ever
#: writing "expired" back to the ``status`` column -- see the module
#: docstring's "expired wrinkle" section. Evaluated against Postgres's own
#: ``now()``, not Python's, so there is exactly one authoritative clock.
_STATUS_CASE_SQL = """
    CASE
        WHEN status = 'revoked' THEN 'revoked'
        WHEN expires_at IS NOT NULL AND expires_at <= now() THEN 'expired'
        ELSE 'active'
    END
"""

_GRANT_COLUMNS = """
    grant_id, agent_principal_id, user_principal_id, expires_at,
    created_at, revoked_at, %s AS status
""" % _STATUS_CASE_SQL


class HiringRepository(object):
    """Repository for ``marketplace.hiring_grants``, ``.grant_capabilities``,
    ``.grant_credential_scopes``, ``.ratings`` and ``.rating_summary``."""

    def __init__(self, db=None):
        # type: (Optional[Database]) -> None
        self._db = db or Database()
        self._identity = IdentityRepository(self._db)

    # -- FK-satisfying helpers (see module docstring) ----------------------

    def _ensure_principal(self, principal_id, principal_type):
        # type: (Optional[str], str) -> None
        if not principal_id:
            return
        if self._identity.principal_exists(principal_id):
            return
        try:
            self._identity.register_principal(principal_id, principal_type)
        except ValueError:
            pass  # lost a race with a concurrent ensure/registration -- fine

    def _ensure_capability(self, conn, capability_id):
        # type: (object, Optional[str]) -> None
        if not capability_id:
            return
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO catalog.capabilities
                    (capability_id, version, description)
                VALUES (%s, '0.0.0-auto',
                        'auto-registered by agent marketplace on first use')
                ON CONFLICT (capability_id) DO NOTHING
                """,
                (capability_id,),
            )

    # -- grants ---------------------------------------------------------------

    def create_grant(
        self,
        agent_principal_id,
        user_principal_id,
        scoped_capabilities,
        credential_scopes=None,
        expires_at=None,
    ):
        # type: (str, str, List[str], Optional[List[dict]], Optional[str]) -> dict
        """Create an active hiring grant; validation happens upstream in
        ``agent_marketplace.app`` (including the real Vault grant call for
        any ``credential_scopes`` -- see module docstring)."""
        self._ensure_principal(agent_principal_id, "agent")
        self._ensure_principal(user_principal_id, "user")
        scoped_capabilities = list(scoped_capabilities)
        credential_scopes = [dict(scope) for scope in (credential_scopes or [])]
        expires_dt = parse_expires_at(expires_at) if expires_at else None
        grant_id = str(uuid.uuid4())

        with self._db.transaction() as conn:
            for capability_id in scoped_capabilities:
                self._ensure_capability(conn, capability_id)

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO marketplace.hiring_grants
                        (grant_id, agent_principal_id, user_principal_id,
                         expires_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (grant_id, agent_principal_id, user_principal_id,
                     expires_dt),
                )

            with conn.cursor() as cur:
                for capability_id in scoped_capabilities:
                    cur.execute(
                        """
                        INSERT INTO marketplace.grant_capabilities
                            (grant_id, capability_id)
                        VALUES (%s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (grant_id, capability_id),
                    )
                for scope in credential_scopes:
                    cur.execute(
                        """
                        INSERT INTO marketplace.grant_credential_scopes
                            (grant_id, credential_id, scope)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (grant_id, credential_id)
                        DO UPDATE SET scope = EXCLUDED.scope
                        """,
                        (grant_id, scope["credential_id"], scope["scope"]),
                    )

            # Re-read through the same status-computing query every other
            # method uses (_STATUS_CASE_SQL) rather than hand-duplicating the
            # predicate here -- correctly reports "expired" even for the
            # pathological case of a caller passing an already-past
            # expires_at at creation time.
            row = self._fetch_grant_row(conn, grant_id)
            return self._grant_view(conn, row)

    def get_grant(self, grant_id):
        # type: (str) -> Optional[dict]
        """Fetch a grant (expiry applied as a query predicate -- see module
        docstring), or ``None`` if unknown."""
        with self._db.connection() as conn:
            row = self._fetch_grant_row(conn, grant_id)
            if row is None:
                return None
            return self._grant_view(conn, row)

    def list_grants(self, agent_principal_id=None, user_principal_id=None):
        # type: (Optional[str], Optional[str]) -> List[dict]
        """Grants filtered by agent and/or user, oldest first.

        Expired-but-not-revoked grants are reported with status "expired"
        (a query predicate, never a stored value -- see module docstring).
        """
        clauses = []
        params = []
        if agent_principal_id is not None:
            clauses.append("agent_principal_id = %s")
            params.append(agent_principal_id)
        if user_principal_id is not None:
            clauses.append("user_principal_id = %s")
            params.append(user_principal_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT %s FROM marketplace.hiring_grants%s "
                    "ORDER BY created_at, grant_id" % (_GRANT_COLUMNS, where),
                    tuple(params),
                )
                rows = cur.fetchall()
            return [self._grant_view(conn, row) for row in rows]

    def revoke_grant(self, grant_id):
        # type: (str) -> Optional[dict]
        """Mark a grant revoked; returns the updated view (None = unknown)."""
        with self._db.transaction() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    UPDATE marketplace.hiring_grants
                    SET status = 'revoked', revoked_at = now()
                    WHERE grant_id = %s
                    RETURNING grant_id, agent_principal_id,
                              user_principal_id, expires_at, created_at,
                              revoked_at, 'revoked' AS status
                    """,
                    (grant_id,),
                )
                row = cur.fetchone()
            if row is None:
                return None
            return self._grant_view(conn, row)

    def has_hiring(self, user_principal_id, agent_principal_id):
        # type: (str, str) -> bool
        """True when the user has any NON-REVOKED hiring grant for the
        agent. An expired hire still counts -- the work happened, so the
        user has standing to rate."""
        with self._db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM marketplace.hiring_grants
                    WHERE user_principal_id = %s
                      AND agent_principal_id = %s
                      AND status != 'revoked'
                    LIMIT 1
                    """,
                    (user_principal_id, agent_principal_id),
                )
                return cur.fetchone() is not None

    def active_hirings_count(self, agent_principal_id):
        # type: (str) -> int
        """Grants for the agent that are active right now (not expired,
        not revoked) -- the query predicate, applied directly in SQL."""
        with self._db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT count(*) FROM marketplace.hiring_grants
                    WHERE agent_principal_id = %s
                      AND status = 'active'
                      AND (expires_at IS NULL OR expires_at > now())
                    """,
                    (agent_principal_id,),
                )
                return cur.fetchone()[0]

    def _fetch_grant_row(self, conn, grant_id):
        # type: (object, str) -> Optional[dict]
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT %s FROM marketplace.hiring_grants "
                "WHERE grant_id = %%s" % _GRANT_COLUMNS,
                (grant_id,),
            )
            return cur.fetchone()

    def _grant_view(self, conn, row):
        # type: (object, dict) -> dict
        """Build the full R10-shaped grant dict: pre-existing consumers read
        ``grant_id``/``agent_principal_id``/``user_principal_id``/
        ``scoped_capabilities``/``credential_scopes``/``expires_at``/
        ``status``/``created_at``/``revoked_at`` off this exact structure."""
        grant_id = row["grant_id"]
        with conn.cursor() as cur:
            cur.execute(
                "SELECT capability_id FROM marketplace.grant_capabilities "
                "WHERE grant_id = %s ORDER BY capability_id",
                (grant_id,),
            )
            scoped_capabilities = [r[0] for r in cur.fetchall()]
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT credential_id, scope "
                "FROM marketplace.grant_credential_scopes "
                "WHERE grant_id = %s ORDER BY credential_id",
                (grant_id,),
            )
            credential_scopes = [dict(r) for r in cur.fetchall()]
        return {
            "grant_id": grant_id,
            "agent_principal_id": row["agent_principal_id"],
            "user_principal_id": row["user_principal_id"],
            "scoped_capabilities": scoped_capabilities,
            "credential_scopes": credential_scopes,
            "expires_at": _iso(row["expires_at"]),
            "status": row["status"],
            "created_at": _iso(row["created_at"]),
            "revoked_at": _iso(row.get("revoked_at")),
        }

    # -- ratings --------------------------------------------------------------

    def set_rating(
        self, agent_principal_id, user_principal_id, rating,
        review_text=None,
    ):
        # type: (str, str, int, Optional[str]) -> dict
        """Insert a NEW rating row (KTD8: append-only history -- re-rating
        the same (agent, user) pair no longer replaces the prior rating,
        both count toward ``rating_summary``'s average forever). The
        ``AFTER INSERT`` trigger in ``migrations/0008_hiring.sql`` keeps
        ``marketplace.rating_summary`` current."""
        self._ensure_principal(agent_principal_id, "agent")
        self._ensure_principal(user_principal_id, "user")
        with self._db.transaction() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO marketplace.ratings
                        (agent_principal_id, user_principal_id, rating,
                         review_text)
                    VALUES (%s, %s, %s, %s)
                    RETURNING *
                    """,
                    (agent_principal_id, user_principal_id, rating,
                     review_text),
                )
                row = cur.fetchone()
        return {
            "rating_id": row["rating_id"],
            "agent_principal_id": row["agent_principal_id"],
            "user_principal_id": row["user_principal_id"],
            "rating": row["rating"],
            "review_text": row["review_text"],
            "created_at": _iso(row["created_at"]),
        }

    def rating_summary(self, agent_principal_id):
        # type: (str) -> Tuple[Optional[float], int]
        """(avg_rating, rating_count); avg is None with no ratings. A single
        indexed point lookup against the materialized
        ``marketplace.rating_summary`` row, not a re-scan of every rating."""
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT avg_rating, review_count "
                    "FROM marketplace.rating_summary "
                    "WHERE agent_principal_id = %s",
                    (agent_principal_id,),
                )
                row = cur.fetchone()
        if row is None or row["review_count"] == 0:
            return None, 0
        return float(row["avg_rating"]), row["review_count"]

    def reviews(self, agent_principal_id):
        # type: (str) -> List[dict]
        """All rating records for the agent, oldest first (full append-only
        history, KTD8 -- not deduplicated by user)."""
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT * FROM marketplace.ratings
                    WHERE agent_principal_id = %s
                    ORDER BY created_at, user_principal_id, rating_id
                    """,
                    (agent_principal_id,),
                )
                rows = cur.fetchall()
        return [
            {
                "rating_id": row["rating_id"],
                "agent_principal_id": row["agent_principal_id"],
                "user_principal_id": row["user_principal_id"],
                "rating": row["rating"],
                "review_text": row["review_text"],
                "created_at": _iso(row["created_at"]),
            }
            for row in rows
        ]


def _iso(value):
    # type: (object) -> object
    return value.isoformat() if isinstance(value, datetime) else value
