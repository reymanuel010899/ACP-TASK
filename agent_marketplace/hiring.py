"""Hiring grants + ratings storage for the Agent Marketplace (unit U8).

The marketplace does NOT store agents — the Registry is the source of truth
for agent identity and reputation. What the marketplace owns locally is:

* hiring grants — a user hires an agent for a set of scoped capabilities,
  optionally tied to Vault credential scopes and an expiry;
* ratings — one rating per (user, agent) pair; re-rating REPLACES the
  previous rating rather than duplicating it.

Thread-safe (a single lock guards all mutation) so it can back the
``ThreadingHTTPServer`` in ``agent_marketplace.app``.
"""

import datetime
import threading
import uuid

from typing import Dict, List, Optional, Tuple


def _utcnow():
    # type: () -> datetime.datetime
    return datetime.datetime.now(datetime.timezone.utc)


def _utcnow_rfc3339():
    # type: () -> str
    return (
        _utcnow().replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def parse_expires_at(value):
    # type: (str) -> datetime.datetime
    """Parse an ISO-8601 timestamp ('Z' suffix accepted); raise ValueError.

    Naive timestamps are interpreted as UTC.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("expires_at must be a non-empty string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def _is_expired(grant, now=None):
    # type: (dict, Optional[datetime.datetime]) -> bool
    expires_at = grant.get("expires_at")
    if not expires_at:
        return False
    try:
        deadline = parse_expires_at(expires_at)
    except ValueError:
        return False  # stored value was validated on the way in
    return (now or _utcnow()) >= deadline


class HiringStore(object):
    """Thread-safe storage for hiring grants and agent ratings."""

    def __init__(self):
        # type: () -> None
        self._lock = threading.RLock()
        # grant_id -> grant dict
        self._grants = {}  # type: Dict[str, dict]
        # agent_principal_id -> {user_principal_id -> rating record}
        self._ratings = {}  # type: Dict[str, Dict[str, dict]]

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
        """Create an active hiring grant; validation happens upstream."""
        grant = {
            "grant_id": str(uuid.uuid4()),
            "agent_principal_id": agent_principal_id,
            "user_principal_id": user_principal_id,
            "scoped_capabilities": list(scoped_capabilities),
            "credential_scopes": [
                dict(scope) for scope in (credential_scopes or [])
            ],
            "expires_at": expires_at,
            "status": "active",
            "created_at": _utcnow_rfc3339(),
        }
        with self._lock:
            self._grants[grant["grant_id"]] = grant
        return self._view(grant)

    def get_grant(self, grant_id):
        # type: (str) -> Optional[dict]
        """Fetch a grant (expiry applied to the reported status)."""
        with self._lock:
            grant = self._grants.get(grant_id)
            return self._view(grant) if grant is not None else None

    def list_grants(self, agent_principal_id=None, user_principal_id=None):
        # type: (Optional[str], Optional[str]) -> List[dict]
        """Grants filtered by agent and/or user, oldest first.

        Expired-but-not-revoked grants are reported with status "expired".
        """
        with self._lock:
            grants = [
                self._view(g)
                for g in self._grants.values()
                if (
                    agent_principal_id is None
                    or g["agent_principal_id"] == agent_principal_id
                )
                and (
                    user_principal_id is None
                    or g["user_principal_id"] == user_principal_id
                )
            ]
        grants.sort(key=lambda g: (g["created_at"], g["grant_id"]))
        return grants

    def revoke_grant(self, grant_id):
        # type: (str) -> Optional[dict]
        """Mark a grant revoked; returns the updated view (None = unknown)."""
        with self._lock:
            grant = self._grants.get(grant_id)
            if grant is None:
                return None
            grant["status"] = "revoked"
            grant["revoked_at"] = _utcnow_rfc3339()
            return self._view(grant)

    def has_hiring(self, user_principal_id, agent_principal_id):
        # type: (str, str) -> bool
        """True when the user has any NON-REVOKED hiring grant for the agent.

        An expired hire still counts — the work happened, so the user has
        standing to rate.
        """
        with self._lock:
            return any(
                g["user_principal_id"] == user_principal_id
                and g["agent_principal_id"] == agent_principal_id
                and g["status"] != "revoked"
                for g in self._grants.values()
            )

    def active_hirings_count(self, agent_principal_id):
        # type: (str) -> int
        """Grants for the agent that are active right now (not expired)."""
        with self._lock:
            return sum(
                1
                for g in self._grants.values()
                if g["agent_principal_id"] == agent_principal_id
                and self._view(g)["status"] == "active"
            )

    def _view(self, grant):
        # type: (dict) -> dict
        """A copy of the grant with lazy expiry applied to its status."""
        view = dict(grant)
        if view["status"] == "active" and _is_expired(view):
            view["status"] = "expired"
        return view

    # -- ratings --------------------------------------------------------------

    def set_rating(
        self, agent_principal_id, user_principal_id, rating,
        review_text=None,
    ):
        # type: (str, str, int, Optional[str]) -> dict
        """Set (or REPLACE) the user's rating of the agent."""
        record = {
            "agent_principal_id": agent_principal_id,
            "user_principal_id": user_principal_id,
            "rating": rating,
            "review_text": review_text,
            "created_at": _utcnow_rfc3339(),
        }
        with self._lock:
            self._ratings.setdefault(agent_principal_id, {})[
                user_principal_id
            ] = record
        return dict(record)

    def rating_summary(self, agent_principal_id):
        # type: (str) -> Tuple[Optional[float], int]
        """(avg_rating, rating_count); avg is None with no ratings."""
        with self._lock:
            records = list(
                self._ratings.get(agent_principal_id, {}).values()
            )
        if not records:
            return None, 0
        total = sum(r["rating"] for r in records)
        return float(total) / len(records), len(records)

    def reviews(self, agent_principal_id):
        # type: (str) -> List[dict]
        """All rating records for the agent, oldest first."""
        with self._lock:
            records = [
                dict(r)
                for r in self._ratings.get(agent_principal_id, {}).values()
            ]
        records.sort(
            key=lambda r: (r["created_at"], r["user_principal_id"])
        )
        return records
