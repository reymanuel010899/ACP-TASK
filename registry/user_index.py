"""Storage for user Principals and their reputation records.

Unit U5 (database architecture): user CRUD now goes through
``libs.identity_repository.IdentityRepository`` (Postgres, ``identity``
schema -- the SAME ``identity.principals`` table ``registry/agent_index.py``
uses for agent Principals, distinguished by ``principal_type``). Reputation
methods delegate to ``libs.reputation_repository.ReputationRepository`` --
the ONE canonical reputation write path shared with Verification Service
(R2; see that module's docstring). ``UserIndex`` keeps its exact
pre-existing public method signatures so ``registry/app.py`` and every
existing test needed no changes here.

Unit U10 (KTD9): the dead ``path`` constructor argument and its
corresponding ``--user-index-path`` CLI flag are removed -- users and
reputation persist via Postgres unconditionally now, so there is nothing
left for a JSON-file path to do.
"""

from typing import Dict, List, Optional

from libs.identity_repository import IdentityRepository
from libs.reputation_repository import ReputationRepository


class UserIndex(object):
    """User Principals and their reputation records (Postgres-backed, unit U5)."""

    def __init__(self, db=None):
        # type: (Optional[object]) -> None
        self._identity = IdentityRepository(db=db)
        self._reputation = ReputationRepository(db=db)

    # -- user registration ----------------------------------------------------

    def create_user(self, principal_id, username=None, public_key=None):
        # type: (str, Optional[str], Optional[str]) -> dict
        """Create a new user; return the user record.

        Key custody (Decision 8): only the PUBLIC side is ever stored — an
        optional ``public_key`` for signature verification; the Registry
        never receives private keys.

        Raises ``ValueError`` on a duplicate ``principal_id`` (mirrors the
        prior in-memory contract so ``RegistryService.register_user`` can
        map it to 409).
        """
        self._identity.register_principal(
            principal_id, "user", display_name=username
        )
        if public_key:
            self._identity.register_key(principal_id, public_key)
        # Registration itself counts as "active": matches the prior
        # in-memory behavior of setting last_active == created_at at
        # creation time (rather than leaving it NULL until the first login).
        self._identity.update_last_active(principal_id)
        # Re-fetch (rather than reuse the pre-update_last_active row) so the
        # returned "last_active" reflects the update just made above.
        return self._user_dict(principal_id, None, username, public_key)

    def get_public_key(self, principal_id):
        # type: (str) -> Optional[str]
        """The user's registered public key, or None (unknown user OR a user
        who registered without one — callers distinguish via user_exists)."""
        key_row = self._identity.get_active_key(principal_id)
        return key_row["public_key"] if key_row is not None else None

    def get_user(self, principal_id):
        # type: (str) -> Optional[dict]
        """Fetch a user record.

        Unit U5 (database architecture): no longer gated on
        ``principal_type == "user"``. Reputation records are unified across
        principal types (R2) -- ``POST /users/{id}/reputation`` already
        accepted agent principals before this unit; this read path only
        gated on type by accident of the pre-U5 two-store split (agents and
        users lived in separate in-memory dicts, so "mirroring" an agent's
        principal_id into the user store — solely to read its per-capability
        breakdown via this endpoint — was a harmless, if odd, workaround).
        Since U2/U5 both types share one ``identity.principals`` table, that
        workaround now collides on the primary key instead. Serving any
        existing principal here (not just type='user') removes the need for
        the workaround rather than papering over the collision.
        """
        principal_row = self._identity.get_principal(principal_id)
        if principal_row is None:
            return None
        return self._user_dict(principal_id, principal_row)

    def user_exists(self, principal_id):
        # type: (str) -> bool
        """Check if a user exists."""
        principal_row = self._identity.get_principal(principal_id)
        return principal_row is not None and principal_row.get("principal_type") == "user"

    def update_last_active(self, principal_id):
        # type: (str) -> None
        """Update last_active timestamp for a user."""
        if self.user_exists(principal_id):
            self._identity.update_last_active(principal_id)

    def _user_dict(self, principal_id, principal_row, username=None, public_key=None):
        # type: (str, dict, Optional[str], Optional[str]) -> dict
        row = principal_row or self._identity.get_principal(principal_id) or {}
        user = {
            "principal_id": principal_id,
            "created_at": _iso(row.get("created_at")),
            "last_active": _iso(row.get("last_active_at")),
        }
        display_name = username if username is not None else row.get("display_name")
        if display_name:
            user["username"] = display_name
        key = public_key
        if key is None:
            key_row = self._identity.get_active_key(principal_id)
            key = key_row["public_key"] if key_row is not None else None
        if key:
            user["public_key"] = key
        return user

    # -- reputation records ---------------------------------------------------

    def get_reputation_records(self, principal_id):
        # type: (str) -> List[dict]
        """Get all reputation records for a user, aggregated by capability."""
        return self._reputation.get_reputation(principal_id)

    def get_reputation_summary(self, principal_id, capability_id):
        # type: (str, str) -> Optional[dict]
        """Get the reputation summary for (principal, capability) pair."""
        records = self._reputation.get_reputation(principal_id, capability_id=capability_id)
        return records[0] if records else None

    def record_reputation(
        self, principal_id, capability_id, task_id, verified
    ):
        # type: (str, str, str, bool) -> dict
        """Record a reputation event (verified or rejected task).

        Updates the aggregated reputation record for this (principal, capability)
        pair and returns the updated record. ``task_id`` is not itself stored
        (the prior in-memory record never persisted it either -- it's an
        audit-log detail, recorded upstream by the caller).
        """
        record = self._reputation.record_verdict(
            principal_id, capability_id, "verified" if verified else "rejected"
        )
        self._identity.update_last_active(principal_id)
        return record

    def get_aggregated_reputation(self, principal_id):
        # type: (str) -> dict
        """Get aggregated reputation summary across all capabilities.

        Returns neutral/zero values if the user has no records.
        """
        records = self.get_reputation_records(principal_id)

        if not records:
            return {
                "tasks_verified": 0,
                "tasks_rejected": 0,
                "verification_rate": None,
            }

        total_verified = sum(r.get("tasks_verified", 0) for r in records)
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


def _iso(value):
    # type: (object) -> object
    try:
        return value.isoformat()
    except AttributeError:
        return value
