"""Storage for the AgentTrust Reference Registry.

Two concerns, one store:

* **Registrations** — ``principal_id -> {principal_id, agent_card,
  registered_at}`` plus a capability index (each ``skills[].id`` on the card
  is a capability id). In-memory by default; when ``path`` is given, the
  registrations are loaded from and saved to that JSON file after every
  mutation (the capability index is rebuilt from the cards on load, so the
  file stays a plain list of registrations).
* **API keys** — the invite keys that gate ``POST /register`` (anti-Sybil
  friction, KTD8). Keys minted at runtime live in memory; ``api_keys_path``
  optionally seeds the set from a JSON array of strings (the file is never
  written back — it is operator-owned input).

Thread-safe (a single lock guards all mutation) so it can back the
``ThreadingHTTPServer`` in ``registry.app``.
"""

import datetime
import json
import os
import secrets
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


def card_capability_ids(agent_card):
    # type: (dict) -> List[str]
    """The capability ids an Agent Card offers: each ``skills[].id``."""
    skills = agent_card.get("skills") or []
    ids = []
    for skill in skills:
        if isinstance(skill, dict) and isinstance(skill.get("id"), str):
            ids.append(skill["id"])
    return ids


class IndexStore(object):
    """Registrations, capability index, and API-key management."""

    def __init__(self, path=None, api_keys_path=None):
        # type: (Optional[str], Optional[str]) -> None
        self._lock = threading.RLock()
        self._path = path

        # principal_id -> registration dict
        self._registrations = {}  # type: Dict[str, dict]
        # capability_id -> set of principal_ids
        self._by_capability = {}  # type: Dict[str, Set[str]]
        # Valid invite/API keys.
        self._api_keys = set()  # type: Set[str]

        if path is not None and os.path.exists(path):
            self._load(path)
        if api_keys_path is not None and os.path.exists(api_keys_path):
            self._load_api_keys(api_keys_path)

    # -- persistence ----------------------------------------------------------

    def _load(self, path):
        # type: (str) -> None
        with open(path) as f:
            registrations = json.load(f)
        if not isinstance(registrations, list):
            raise ValueError("index file must contain a JSON array")
        for registration in registrations:
            self._index(registration)

    def _load_api_keys(self, path):
        # type: (str) -> None
        with open(path) as f:
            keys = json.load(f)
        if not isinstance(keys, list):
            raise ValueError("api keys file must contain a JSON array")
        self._api_keys.update(str(k) for k in keys)

    def _save(self):
        # type: () -> None
        if self._path is None:
            return
        registrations = sorted(
            self._registrations.values(), key=lambda r: r["principal_id"]
        )
        with open(self._path, "w") as f:
            json.dump(registrations, f, indent=2, sort_keys=True)

    # -- registrations ---------------------------------------------------------

    def _index(self, registration):
        # type: (dict) -> None
        principal_id = registration["principal_id"]
        previous = self._registrations.get(principal_id)
        if previous is not None:
            for capability_id in card_capability_ids(previous["agent_card"]):
                self._by_capability.get(capability_id, set()).discard(
                    principal_id
                )
        self._registrations[principal_id] = registration
        for capability_id in card_capability_ids(registration["agent_card"]):
            self._by_capability.setdefault(capability_id, set()).add(
                principal_id
            )

    def register(self, principal_id, agent_card):
        # type: (str, dict) -> dict
        """Store (or replace) a registration; index its capabilities."""
        registration = {
            "principal_id": principal_id,
            "agent_card": agent_card,
            "registered_at": _utcnow_rfc3339(),
        }
        with self._lock:
            self._index(registration)
            self._save()
            return registration

    def get(self, principal_id):
        # type: (str) -> Optional[dict]
        with self._lock:
            return self._registrations.get(principal_id)

    def find_by_capability(self, capability_id):
        # type: (str) -> List[dict]
        """Registrations offering the capability, ordered by principal_id."""
        with self._lock:
            principal_ids = sorted(self._by_capability.get(capability_id, ()))
            return [self._registrations[pid] for pid in principal_ids]

    # -- API keys ---------------------------------------------------------------

    def issue_api_key(self):
        # type: () -> str
        """Mint a new invite/API key and remember it as valid."""
        key = "atk_%s" % secrets.token_urlsafe(24)
        with self._lock:
            self._api_keys.add(key)
        return key

    def is_valid_api_key(self, key):
        # type: (object) -> bool
        if not isinstance(key, str) or not key:
            return False
        with self._lock:
            return key in self._api_keys
