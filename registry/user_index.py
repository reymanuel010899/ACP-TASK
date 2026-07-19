"""Storage for user Principals and their reputation records.

Parallel to the agent registration layer, this module manages:

* **User Principals** — ``principal_id -> {principal_id, username,
  created_at, last_active}`` plus reputation records. In-memory by default;
  when ``path`` is given, the data is persisted to JSON after every mutation.

* **Reputation Records** — aggregated reputation per (principal, capability)
  pair, mirroring the RFC-0001 reputation record structure:
  {principal_id, capability_id, tasks_verified, tasks_rejected,
  verification_rate, updated_at}.

Thread-safe (a single lock guards all mutation) so it can back the
``ThreadingHTTPServer`` in ``registry.app``.
"""

import datetime
import json
import os
import threading

from typing import Dict, List, Optional, Set


def _utcnow_rfc3339():
    # type: () -> str
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


class UserIndex(object):
    """User Principals and their reputation records."""

    def __init__(self, path=None):
        # type: (Optional[str]) -> None
        self._lock = threading.RLock()
        self._path = path

        # principal_id -> user dict
        self._users = {}  # type: Dict[str, dict]
        # (principal_id, capability_id) -> reputation record dict
        self._reputation_records = {}  # type: Dict[tuple, dict]

        if path is not None and os.path.exists(path):
            self._load(path)

    # -- persistence ----------------------------------------------------------

    def _load(self, path):
        # type: (str) -> None
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("user index file must contain a JSON object")

        users = data.get("users", {})
        if isinstance(users, dict):
            self._users = users

        reputation = data.get("reputation_records", [])
        if isinstance(reputation, list):
            for record in reputation:
                if isinstance(record, dict):
                    principal_id = record.get("principal_id")
                    capability_id = record.get("capability_id")
                    if principal_id and capability_id:
                        key = (principal_id, capability_id)
                        self._reputation_records[key] = record

    def _save(self):
        # type: () -> None
        if self._path is None:
            return
        data = {
            "users": self._users,
            "reputation_records": list(self._reputation_records.values()),
        }
        with open(self._path, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)

    # -- user registration ----------------------------------------------------

    def create_user(self, principal_id, username=None):
        # type: (str, Optional[str]) -> dict
        """Create a new user; return the user record."""
        now = _utcnow_rfc3339()
        user = {
            "principal_id": principal_id,
            "created_at": now,
            "last_active": now,
        }
        if username:
            user["username"] = username
        with self._lock:
            self._users[principal_id] = user
            self._save()
            return user

    def get_user(self, principal_id):
        # type: (str) -> Optional[dict]
        """Fetch a user record."""
        with self._lock:
            return self._users.get(principal_id)

    def user_exists(self, principal_id):
        # type: (str) -> bool
        """Check if a user exists."""
        with self._lock:
            return principal_id in self._users

    def update_last_active(self, principal_id):
        # type: (str) -> None
        """Update last_active timestamp for a user."""
        user = self.get_user(principal_id)
        if user is not None:
            with self._lock:
                user["last_active"] = _utcnow_rfc3339()
                self._save()

    # -- reputation records ---------------------------------------------------

    def get_reputation_records(self, principal_id):
        # type: (str) -> List[dict]
        """Get all reputation records for a user, aggregated by capability."""
        with self._lock:
            records = []
            for (pid, _), record in self._reputation_records.items():
                if pid == principal_id:
                    records.append(record)
            return records

    def get_reputation_summary(self, principal_id, capability_id):
        # type: (str, str) -> Optional[dict]
        """Get the reputation summary for (principal, capability) pair."""
        with self._lock:
            key = (principal_id, capability_id)
            return self._reputation_records.get(key)

    def record_reputation(
        self, principal_id, capability_id, task_id, verified
    ):
        # type: (str, str, str, bool) -> dict
        """Record a reputation event (verified or rejected task).

        Updates the aggregated reputation record for this (principal, capability)
        pair and returns the updated record.
        """
        with self._lock:
            key = (principal_id, capability_id)
            now = _utcnow_rfc3339()

            # Get or create the record
            if key not in self._reputation_records:
                record = {
                    "principal_id": principal_id,
                    "capability_id": capability_id,
                    "tasks_verified": 0,
                    "tasks_rejected": 0,
                    "verification_rate": None,
                    "updated_at": now,
                }
            else:
                record = self._reputation_records[key]

            # Update counts
            if verified:
                record["tasks_verified"] += 1
            else:
                record["tasks_rejected"] += 1

            # Recalculate verification_rate
            total = record["tasks_verified"] + record["tasks_rejected"]
            if total > 0:
                record["verification_rate"] = (
                    float(record["tasks_verified"]) / float(total)
                )
            else:
                record["verification_rate"] = None

            record["updated_at"] = now

            # Store and persist
            self._reputation_records[key] = record
            self._save()

            # Update last_active for the user
            if principal_id in self._users:
                self._users[principal_id]["last_active"] = now

            return record

    def get_aggregated_reputation(self, principal_id):
        # type: (str) -> dict
        """Get aggregated reputation summary across all capabilities.

        Returns neutral/zero values if the user has no records.
        """
        with self._lock:
            records = self.get_reputation_records(principal_id)

            if not records:
                return {
                    "tasks_verified": 0,
                    "tasks_rejected": 0,
                    "verification_rate": None,
                }

            total_verified = sum(
                r.get("tasks_verified", 0) for r in records
            )
            total_rejected = sum(r.get("tasks_rejected", 0) for r in records)
            total = total_verified + total_rejected

            return {
                "tasks_verified": total_verified,
                "tasks_rejected": total_rejected,
                "verification_rate": (
                    float(total_verified) / float(total)
                    if total > 0
                    else None
                ),
            }
