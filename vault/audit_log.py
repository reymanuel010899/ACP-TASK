"""Append-only, thread-safe, in-memory audit log for the Vault (unit U7).

Every credential access attempt (granted or denied) and every keyring
rotation is recorded. Entries are immutable once appended and are returned
in insertion order.
"""

import threading
from datetime import datetime
from typing import Dict, List, Optional


class AuditLog:
    """Append-only in-memory audit log, queryable by principal_id."""

    def __init__(self):
        # type: () -> None
        self._entries = []  # type: List[dict]
        self._lock = threading.Lock()

    def append(self, principal_id, action, status,
               credential_id=None, **extra):
        # type: (str, str, str, Optional[str], **str) -> dict
        """Append an entry; returns a copy of what was recorded."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "principal_id": principal_id,
            "credential_id": credential_id,
            "action": action,
            "status": status,
        }
        entry.update(extra)
        with self._lock:
            self._entries.append(entry)
        return dict(entry)

    def query(self, principal_id):
        # type: (str) -> List[dict]
        """All entries for a principal, oldest first (copies)."""
        with self._lock:
            return [
                dict(e)
                for e in self._entries
                if e["principal_id"] == principal_id
            ]

    def all_entries(self):
        # type: () -> List[dict]
        with self._lock:
            return [dict(e) for e in self._entries]
