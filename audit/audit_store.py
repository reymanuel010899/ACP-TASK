"""Append-only, thread-safe, in-memory store for the central audit
service (Phase B, unit U12).

Immutability is part of the contract: this class deliberately exposes NO
update or delete API of any kind. Once appended, an entry can only ever be
read back (as a copy). The store generalizes the Vault-local
``vault.audit_log.AuditLog`` (U7) into an ecosystem-wide log: entries carry
an open-vocabulary ``activity_type`` instead of a vault-specific action.
"""

import threading
import uuid
from datetime import datetime, timezone
from typing import List, Optional


def _utc_now_rfc3339():
    # type: () -> str
    """Current UTC time as an RFC 3339 timestamp (explicit +00:00 offset)."""
    return datetime.now(timezone.utc).isoformat()


def _parse_rfc3339(value):
    # type: (str) -> datetime
    """Parse an RFC 3339 timestamp ('Z' suffix accepted). Raises ValueError."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class AuditStore:
    """Append-only in-memory audit store, queryable with filters."""

    def __init__(self):
        # type: () -> None
        self._entries = []  # type: List[dict]
        self._lock = threading.Lock()

    def append(self, entry):
        # type: (dict) -> dict
        """Record an entry, assigning ``entry_id`` and a server-side
        RFC 3339 UTC ``timestamp``. Returns a copy of what was recorded."""
        record = dict(entry)
        record["entry_id"] = str(uuid.uuid4())
        record["timestamp"] = _utc_now_rfc3339()
        with self._lock:
            self._entries.append(record)
        return dict(record)

    def query(self, principal_id=None, activity_type=None, start_time=None,
              end_time=None, resource_id=None, limit=100):
        # type: (Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], Optional[int]) -> List[dict]
        """Matching entries, NEWEST FIRST, as copies.

        ``start_time``/``end_time`` are inclusive RFC 3339 bounds (raise
        ``ValueError`` if unparseable). ``limit=None`` means unlimited.
        """
        matched = self.query_all(
            principal_id=principal_id,
            activity_type=activity_type,
            start_time=start_time,
            end_time=end_time,
            resource_id=resource_id,
        )
        if limit is not None:
            matched = matched[:limit]
        return matched

    def query_all(self, principal_id=None, activity_type=None,
                  start_time=None, end_time=None, resource_id=None):
        # type: (Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]) -> List[dict]
        """All matching entries (no limit), newest first, as copies."""
        start = _parse_rfc3339(start_time) if start_time else None
        end = _parse_rfc3339(end_time) if end_time else None

        with self._lock:
            snapshot = list(self._entries)

        matched = []
        # Newest first == reverse insertion order (server-assigned times
        # are monotonic per insertion, but insertion order is authoritative).
        for entry in reversed(snapshot):
            if principal_id is not None and (
                entry.get("principal_id") != principal_id
            ):
                continue
            if activity_type is not None and (
                entry.get("activity_type") != activity_type
            ):
                continue
            if resource_id is not None and (
                entry.get("resource_id") != resource_id
            ):
                continue
            if start is not None or end is not None:
                ts = _parse_rfc3339(entry["timestamp"])
                if start is not None and ts < start:
                    continue
                if end is not None and ts > end:
                    continue
            matched.append(dict(entry))
        return matched
