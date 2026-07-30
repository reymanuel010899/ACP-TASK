"""Registrations and API-key management for the AgentTrust Reference Registry.

Unit U5: this module is now a thin wrapper over
:class:`registry.repository.RegistryRepository` (Postgres, ``registry``
schema) -- the actual persistence logic moved to ``registry/repository.py``
so it's shared with ``registry/agent_index.py`` and
``registry/app_registry.py`` against the same tables. ``IndexStore`` keeps
its exact pre-existing public method signatures so ``registry/app.py`` and
every existing test needed no changes here.

Unit U10 (KTD9): the dead ``path`` constructor argument and its
corresponding ``--index-path`` CLI flag are removed -- registrations
persist via Postgres unconditionally now, so there is nothing left for a
JSON-file path to do. ``api_keys_path`` stays: it seeds the given raw keys
as valid, hashed the same way a minted key is (R8) -- this is genuinely
still needed (``tests/registry/test_agent_registration.py``'s
``test_api_keys_seeded_from_file`` exercises it).
"""

import json
import os

from typing import List, Optional

from registry.repository import RegistryRepository


def card_capability_ids(agent_card):
    # type: (dict) -> List[str]
    """The capability ids an Agent Card offers: each ``skills[].id`` --
    the legacy (``POST /register``) extraction convention. See
    ``registry/repository.py``'s docstring for why this convention and
    ``AgentIndex``'s ``agent_card["capabilities"]`` list convention both
    stay, backed by the same indexed tables."""
    skills = agent_card.get("skills") or []
    ids = []
    for skill in skills:
        if isinstance(skill, dict) and isinstance(skill.get("id"), str):
            ids.append(skill["id"])
    return ids


class IndexStore(object):
    """Registrations, capability index, and API-key management (Postgres-backed,
    unit U5)."""

    def __init__(self, api_keys_path=None, db=None):
        # type: (Optional[str], Optional[object]) -> None
        self._repo = RegistryRepository(db=db)
        if api_keys_path is not None and os.path.exists(api_keys_path):
            self._seed_api_keys(api_keys_path)

    def _seed_api_keys(self, path):
        # type: (str) -> None
        with open(path) as f:
            keys = json.load(f)
        if not isinstance(keys, list):
            raise ValueError("api keys file must contain a JSON array")
        for key in keys:
            self._repo.seed_api_key(str(key))

    # -- registrations ---------------------------------------------------------

    def register(self, principal_id, agent_card):
        # type: (str, dict) -> dict
        """Store (or replace) a registration; index its capabilities."""
        return self._repo.register_registration(
            principal_id, agent_card, card_capability_ids(agent_card)
        )

    def get(self, principal_id):
        # type: (str) -> Optional[dict]
        return self._repo.get_registration(principal_id)

    def find_by_capability(self, capability_id):
        # type: (str) -> List[dict]
        """Registrations offering the capability, ordered by principal_id."""
        return self._repo.find_registrations_by_capability(capability_id)

    def list_capabilities(self):
        # type: () -> List[dict]
        """The capability catalog with card-derived context (name,
        description, tags) and the agents declaring each capability."""
        return self._repo.list_capabilities()

    # -- API keys ---------------------------------------------------------------

    def issue_api_key(self):
        # type: () -> str
        """Mint a new invite/API key and remember it as valid. The raw token
        is returned ONCE, here; only its hash is ever stored (R8)."""
        return self._repo.issue_api_key()

    def is_valid_api_key(self, key):
        # type: (object) -> bool
        return self._repo.is_valid_api_key(key)
