"""Postgres-backed storage for the central Audit & Compliance service
(unit U4, ``audit`` schema -- ``migrations/0004_audit.sql``).

Replaces ``audit/audit_store.py``'s in-memory, lock-guarded ``List[dict]``.
Immutability is part of the contract, same as before: this class exposes NO
update/delete API of any kind -- append and query only. Here that
in-Python contract is now backed by a real database-level guarantee too
(``REVOKE UPDATE, DELETE`` + no-op rules in the migration), so even a bug
that somehow called raw SQL against this table directly could not mutate or
remove a row.

Every entry's ``entry_id`` is a ULID (KTD4) rather than a ``uuid4`` string --
time-sortable, so it doubles as a stable tie-breaker ordering key alongside
``created_at`` (see :meth:`query`'s ``ORDER BY``).

Partitioning: ``audit.audit_log`` is range-partitioned by month
(``created_at``). ``migrations/0004_audit.sql`` creates the current and next
month's partitions at migration time, but a static SQL file can't know what
"current month" will be when a real write eventually happens (demo
environments can sit unmigrated for a while, or the migration can simply go
stale). :meth:`append` defensively issues a ``CREATE TABLE IF NOT EXISTS
... PARTITION OF`` for whatever month ``now()`` actually falls in before
every insert, so writes are self-healing and never depend on an external
cron job for this plan's scope.

Uses ``libs.db.Database`` for every connection -- no hand-rolled psycopg
connection handling here (KTD1).
"""

import json
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from psycopg import sql
from psycopg.rows import dict_row

from libs.db import Database
from libs.ulid import generate_ulid


def _utc_now():
    # type: () -> datetime
    return datetime.now(timezone.utc)


def _parse_rfc3339(value):
    # type: (str) -> datetime
    """Parse an RFC 3339 timestamp ('Z' suffix accepted). Raises ValueError."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _partition_bounds(moment):
    # type: (datetime) -> Tuple[str, str, str]
    """``(partition_name, range_start, range_end)`` for the calendar month
    containing ``moment``, e.g. ``("audit_log_2026_07", "2026-07-01",
    "2026-08-01")``."""
    year, month = moment.year, moment.month
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1
    name = "audit_log_%04d_%02d" % (year, month)
    start = "%04d-%02d-01" % (year, month)
    end = "%04d-%02d-01" % (next_year, next_month)
    return name, start, end


class AuditRepository(object):
    """Repository for ``audit.*`` tables: the append-only ``audit_log``."""

    def __init__(self, db=None):
        # type: (Optional[Database]) -> None
        self._db = db or Database()

    # -- partition self-healing --------------------------------------------

    def _ensure_partition(self, conn, moment):
        # type: (object, datetime) -> None
        """Idempotently create the monthly partition ``moment`` falls into,
        in case the migration's hardcoded partitions have gone stale (see
        module docstring). Safe to call on every write -- ``IF NOT EXISTS``
        makes it a no-op once the partition exists."""
        name, start, end = _partition_bounds(moment)
        with conn.cursor() as cur:
            # Literal (not parameterized) dates: psycopg can't infer a
            # parameter's type inside a DDL statement's FOR VALUES FROM/TO
            # clause ("could not determine data type of parameter"), so the
            # bounds are safely embedded as SQL literals instead --
            # sql.Literal quotes them exactly like a bound parameter would,
            # and both values are computed here from `moment`, never from
            # unsanitized caller input.
            cur.execute(
                sql.SQL(
                    "CREATE TABLE IF NOT EXISTS audit.{partition} "
                    "PARTITION OF audit.audit_log "
                    "FOR VALUES FROM ({start}) TO ({end})"
                ).format(
                    partition=sql.Identifier(name),
                    start=sql.Literal(start),
                    end=sql.Literal(end),
                )
            )

    # -- append --------------------------------------------------------------

    def append(self, principal_id, activity_type, status,
               resource_type=None, resource_id=None, organization_id=None,
               details=None):
        # type: (str, str, str, Optional[str], Optional[str], Optional[str], Optional[dict]) -> dict
        """Record one entry; returns the stored row (``entry_id`` and
        ``created_at`` are server-assigned)."""
        entry_id = generate_ulid()
        now = _utc_now()
        with self._db.transaction() as conn:
            self._ensure_partition(conn, now)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO audit.audit_log
                        (entry_id, created_at, principal_id, activity_type,
                         status, resource_type, resource_id, organization_id,
                         details)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    RETURNING *
                    """,
                    (
                        entry_id, now, principal_id, activity_type, status,
                        resource_type, resource_id, organization_id,
                        _dumps(details or {}),
                    ),
                )
                return _normalize(cur.fetchone())

    # -- query -----------------------------------------------------------------

    def query(self, principal_id=None, activity_type=None,
              resource_type=None, resource_id=None, organization_id=None,
              start_time=None, end_time=None, limit=100):
        # type: (Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], Optional[int]) -> Tuple[List[dict], int]
        """Matching entries, NEWEST FIRST, plus the FULL match count
        (ignoring ``limit``) as ``(entries, total_matched)``.

        ``start_time``/``end_time`` are inclusive RFC 3339 bounds (raises
        ``ValueError`` if unparseable, exactly like ``audit_store.AuditStore``
        did). ``limit=None`` means unlimited.
        """
        start = _parse_rfc3339(start_time) if start_time else None
        end = _parse_rfc3339(end_time) if end_time else None

        where_sql, params = _build_where(
            principal_id, activity_type, resource_type, resource_id,
            organization_id, start, end,
        )

        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT count(*) AS total FROM audit.audit_log WHERE "
                    + where_sql,
                    params,
                )
                total = cur.fetchone()["total"]

                query_sql = (
                    "SELECT * FROM audit.audit_log WHERE " + where_sql
                    + " ORDER BY created_at DESC, entry_id DESC"
                )
                q_params = list(params)
                if limit is not None:
                    query_sql += " LIMIT %s"
                    q_params.append(limit)
                cur.execute(query_sql, q_params)
                entries = [_normalize(row) for row in cur.fetchall()]

        return entries, total

    def query_all(self, principal_id=None, activity_type=None,
                  resource_type=None, resource_id=None,
                  organization_id=None, start_time=None, end_time=None):
        # type: (Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]) -> List[dict]
        """All matching entries (no limit), newest first. A thin convenience
        wrapper over :meth:`query` for callers that only want the rows."""
        entries, _total = self.query(
            principal_id=principal_id, activity_type=activity_type,
            resource_type=resource_type, resource_id=resource_id,
            organization_id=organization_id, start_time=start_time,
            end_time=end_time, limit=None,
        )
        return entries


def _build_where(principal_id, activity_type, resource_type, resource_id,
                  organization_id, start, end):
    # type: (Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], Optional[datetime], Optional[datetime]) -> Tuple[str, list]
    clauses = []
    params = []  # type: list
    if principal_id is not None:
        clauses.append("principal_id = %s")
        params.append(principal_id)
    if activity_type is not None:
        clauses.append("activity_type = %s")
        params.append(activity_type)
    if resource_type is not None:
        clauses.append("resource_type = %s")
        params.append(resource_type)
    if resource_id is not None:
        clauses.append("resource_id = %s")
        params.append(resource_id)
    if organization_id is not None:
        clauses.append("organization_id = %s")
        params.append(organization_id)
    if start is not None:
        clauses.append("created_at >= %s")
        params.append(start)
    if end is not None:
        clauses.append("created_at <= %s")
        params.append(end)
    where_sql = " AND ".join(clauses) if clauses else "TRUE"
    return where_sql, params


def _dumps(value):
    # type: (dict) -> str
    """JSON-encode a dict for a ``jsonb`` column parameter."""
    return json.dumps(value)


def _normalize(row):
    # type: (Optional[dict]) -> Optional[dict]
    """Convert a fetched row's ``timestamptz`` values to ISO-8601 strings,
    so repository return values are JSON-serializable exactly like the
    record dicts the prior in-memory ``AuditStore`` built by hand."""
    if row is None:
        return None
    return {
        key: (value.isoformat() if isinstance(value, datetime) else value)
        for key, value in row.items()
    }
