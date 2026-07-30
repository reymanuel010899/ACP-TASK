"""Storage for Agent Principals (Phase B, unit U5; Postgres-backed, unit U5
database-architecture).

Unit U5 (database architecture): this module is now a thin wrapper over
:class:`registry.repository.RegistryRepository` (Postgres, ``registry`` +
``identity`` schemas) -- the actual persistence logic moved to
``registry/repository.py`` so it's shared with ``registry/index_store.py``
against the same ``registry.agents``/``registry.agent_capabilities`` tables
(see that module's docstring for how the two registration paths coexist).
``AgentIndex`` keeps its exact pre-existing public method signatures so
``registry/app.py`` and every existing test needed no changes here.

Agents are first-class Principals: each registers under its own
``principal_id``, is created *by* a user Principal (``created_by``), and
accrues reputation independently — through the same reputation records the
user layer uses (``registry.user_index``), keyed by the agent's own
``principal_id``.

Key custody (Decision 8): only the PUBLIC side of an agent's identity is
ever registered here — ``principal_id`` plus an optional ``public_key`` for
future signature verification. The Registry never receives private keys.
"""

from typing import List, Optional

from registry.repository import RegistryRepository


class AgentIndex(object):
    """Agent Principals registered as first-class entities (Postgres-backed,
    unit U5)."""

    def __init__(self, db=None):
        # type: (Optional[object]) -> None
        self._repo = RegistryRepository(db=db)

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
        capabilities = agent_card.get("capabilities") or []
        return self._repo.register_agent_principal(
            principal_id, agent_card, created_by, capabilities,
            public_key=public_key,
        )

    # -- lookup ---------------------------------------------------------------

    def get_agent(self, principal_id):
        # type: (str) -> Optional[dict]
        """Fetch an agent record."""
        return self._repo.get_agent_principal(principal_id)

    def agent_exists(self, principal_id):
        # type: (str) -> bool
        """Check if an agent Principal exists."""
        return self._repo.agent_principal_exists(principal_id)

    def find_by_capability(self, capability_id):
        # type: (str) -> List[dict]
        """All agents whose card declares ``capability_id`` (may be empty)."""
        return self._repo.find_agent_principals_by_capability(capability_id)

    def all_agents(self):
        # type: () -> List[dict]
        """Every registered agent record (registration order)."""
        return self._repo.list_agent_principals()
