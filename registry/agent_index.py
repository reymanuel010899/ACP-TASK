"""Storage for Agent Principals (Phase B, unit U5).

Agents are first-class Principals: each registers under its own
``principal_id``, is created *by* a user Principal (``created_by``), and
accrues reputation independently — through the same reputation records the
user layer uses (``registry.user_index``), keyed by the agent's own
``principal_id``.

Key custody (Decision 8): only the PUBLIC side of an agent's identity is
ever registered here — ``principal_id`` plus an optional ``public_key`` for
future signature verification. The Registry never receives private keys.

Thread-safe (a single lock guards all mutation) so it can back the
``ThreadingHTTPServer`` in ``registry.app``.
"""

import datetime
import threading

from typing import Dict, List, Optional


def _utcnow_rfc3339():
    # type: () -> str
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


class AgentIndex(object):
    """Agent Principals registered as first-class entities."""

    def __init__(self):
        # type: () -> None
        self._lock = threading.RLock()
        # principal_id -> agent dict
        self._agents = {}  # type: Dict[str, dict]

    # -- registration ---------------------------------------------------------

    def register_agent(
        self, principal_id, agent_card, created_by, public_key=None
    ):
        # type: (str, dict, str, Optional[str]) -> dict
        """Register a new agent Principal; return the stored agent record.

        Assumes validation happened upstream (``RegistryService``); raises
        ``ValueError`` on a duplicate principal_id so callers can map it to
        409.
        """
        now = _utcnow_rfc3339()
        agent = {
            "principal_id": principal_id,
            "agent_card": agent_card,
            "created_by": created_by,
            "created_at": now,
            "registered_at": now,
        }
        if public_key:
            agent["public_key"] = public_key
        with self._lock:
            if principal_id in self._agents:
                raise ValueError(
                    "agent principal_id already registered: %s" % principal_id
                )
            self._agents[principal_id] = agent
            return agent

    # -- lookup ---------------------------------------------------------------

    def get_agent(self, principal_id):
        # type: (str) -> Optional[dict]
        """Fetch an agent record."""
        with self._lock:
            return self._agents.get(principal_id)

    def agent_exists(self, principal_id):
        # type: (str) -> bool
        """Check if an agent Principal exists."""
        with self._lock:
            return principal_id in self._agents

    def find_by_capability(self, capability_id):
        # type: (str) -> List[dict]
        """All agents whose card declares ``capability_id`` (may be empty)."""
        with self._lock:
            matches = []
            for agent in self._agents.values():
                capabilities = agent["agent_card"].get("capabilities", [])
                if capability_id in capabilities:
                    matches.append(agent)
            return matches
