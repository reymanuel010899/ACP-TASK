"""Hiring grants + ratings storage for the Agent Marketplace (unit U8).

The marketplace does NOT store agents — the Registry is the source of truth
for agent identity and reputation. What the marketplace owns locally is:

* hiring grants — a user hires an agent for a set of scoped capabilities,
  optionally tied to Vault credential scopes and an expiry;
* ratings — one rating PER SUBMISSION (agent, user, rating) triple, kept as
  append-only history (KTD8): re-rating the same (agent, user) pair inserts
  a new row rather than replacing the prior one, and
  ``marketplace.rating_summary``'s average is computed across every rating
  ever submitted, not just the latest.

``HiringStore`` is now a thin, backward-compatible facade over
``agent_marketplace.repository.HiringRepository`` (Postgres-backed,
``marketplace.hiring_grants``/``.ratings`` -- migrations/0008_hiring.sql):
every method below keeps its EXACT pre-existing name and signature (R10), so
``agent_marketplace/app.py`` needed no changes at all — only where a grant or
rating actually lives changed, not the shape any caller sees. The in-memory
dicts and ``threading.RLock`` this class used to hold directly are gone;
Postgres is now the only source of truth, and it survives a process restart.
"""

from typing import List, Optional, Tuple

from agent_marketplace.repository import HiringRepository, parse_expires_at
from libs.db import Database

# Re-exported so ``from agent_marketplace.hiring import parse_expires_at``
# (agent_marketplace/app.py's pre-existing import) keeps working unchanged;
# the implementation lives in agent_marketplace/repository.py, which also
# needs it and cannot import it back from here without a cycle (see that
# module's docstring for parse_expires_at).
__all__ = ["HiringStore", "parse_expires_at"]


class HiringStore(object):
    """Backward-compatible facade over :class:`agent_marketplace.repository.
    HiringRepository` -- see module docstring."""

    def __init__(self, db=None):
        # type: (Optional[Database]) -> None
        self._repo = HiringRepository(db)

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
        return self._repo.create_grant(
            agent_principal_id,
            user_principal_id,
            scoped_capabilities,
            credential_scopes=credential_scopes,
            expires_at=expires_at,
        )

    def get_grant(self, grant_id):
        # type: (str) -> Optional[dict]
        """Fetch a grant (expiry applied as a query predicate)."""
        return self._repo.get_grant(grant_id)

    def list_grants(self, agent_principal_id=None, user_principal_id=None):
        # type: (Optional[str], Optional[str]) -> List[dict]
        """Grants filtered by agent and/or user, oldest first.

        Expired-but-not-revoked grants are reported with status "expired"
        (a query predicate evaluated by Postgres, never a value this store
        writes).
        """
        return self._repo.list_grants(
            agent_principal_id=agent_principal_id,
            user_principal_id=user_principal_id,
        )

    def revoke_grant(self, grant_id):
        # type: (str) -> Optional[dict]
        """Mark a grant revoked; returns the updated view (None = unknown)."""
        return self._repo.revoke_grant(grant_id)

    def has_hiring(self, user_principal_id, agent_principal_id):
        # type: (str, str) -> bool
        """True when the user has any NON-REVOKED hiring grant for the agent.

        An expired hire still counts — the work happened, so the user has
        standing to rate.
        """
        return self._repo.has_hiring(user_principal_id, agent_principal_id)

    def active_hirings_count(self, agent_principal_id):
        # type: (str) -> int
        """Grants for the agent that are active right now (not expired)."""
        return self._repo.active_hirings_count(agent_principal_id)

    # -- ratings --------------------------------------------------------------

    def set_rating(
        self, agent_principal_id, user_principal_id, rating,
        review_text=None,
    ):
        # type: (str, str, int, Optional[str]) -> dict
        """Record a NEW rating from the user for the agent (KTD8:
        append-only history — a second rating from the same user does NOT
        replace the first; both count toward ``rating_summary`` forever)."""
        return self._repo.set_rating(
            agent_principal_id, user_principal_id, rating,
            review_text=review_text,
        )

    def rating_summary(self, agent_principal_id):
        # type: (str) -> Tuple[Optional[float], int]
        """(avg_rating, rating_count); avg is None with no ratings."""
        return self._repo.rating_summary(agent_principal_id)

    def reviews(self, agent_principal_id):
        # type: (str) -> List[dict]
        """All rating records for the agent, oldest first."""
        return self._repo.reviews(agent_principal_id)
