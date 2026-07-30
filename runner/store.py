"""Agent-definition store for the runner (U1).

A definition is the *spec* of a managed agent (name, template, capabilities,
pricing) plus the runner-assigned paths (``keys_dir``, ``log_path``). It is
persisted to a JSON file under ``data_dir`` so definitions survive a runner
restart (they come back as ``stopped``). Live runtime state (pid/port/url/
status) is NOT stored here -- the supervisor owns that (U3).
"""

import json
import os
import threading
import uuid

try:  # datetime.UTC exists on 3.11+; fall back for 3.9
    from datetime import datetime, timezone

    def _utcnow_rfc3339():
        # type: () -> str
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
except Exception:  # pragma: no cover
    import time

    def _utcnow_rfc3339():
        # type: () -> str
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class DefinitionStore(object):
    """Thread-safe, JSON-persisted store of agent definitions."""

    def __init__(self, data_dir):
        # type: (str) -> None
        self._lock = threading.RLock()
        self._data_dir = data_dir
        self._defs_path = os.path.join(data_dir, "definitions.json")
        self._keys_root = os.path.join(data_dir, "keys")
        self._logs_root = os.path.join(data_dir, "logs")
        os.makedirs(self._keys_root, exist_ok=True)
        os.makedirs(self._logs_root, exist_ok=True)
        self._defs = {}  # type: dict
        self._load()

    # -- persistence ----------------------------------------------------------

    def _load(self):
        # type: () -> None
        if not os.path.exists(self._defs_path):
            return
        try:
            with open(self._defs_path, "r") as fh:
                raw = json.load(fh)
        except (ValueError, OSError):
            return
        if isinstance(raw, dict):
            self._defs = {
                k: v for k, v in raw.items() if isinstance(v, dict)
            }

    def _flush(self):
        # type: () -> None
        tmp = self._defs_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(self._defs, fh, indent=2, sort_keys=True)
        os.replace(tmp, self._defs_path)

    # -- CRUD -----------------------------------------------------------------

    def create(self, name, template, capabilities, description="",
               version="0.1.0", list_price=None, min_price=None, owner=None):
        # type: (str, str, list, str, str, float, float, str) -> dict
        """Create and persist a MANAGED definition; returns the stored record.

        ``owner`` is the principal_id of the USER who added this agent — the
        only identity allowed to mutate it (start/stop/delete)."""
        agent_id = "agt_" + uuid.uuid4().hex[:12]
        definition = {
            "id": agent_id,
            "kind": "managed",
            "owner_principal_id": owner,
            "name": name,
            "description": description,
            "version": version,
            "template": template,
            "capabilities": list(capabilities),
            "list_price": list_price,
            "min_price": min_price,
            "endpoint_url": None,
            "principal_id": None,
            # Managed agents mint and hold their own ed25519 identity at deploy,
            # so they are self-asserting by construction.
            "trust_tier": "verified",
            "keys_dir": os.path.join(self._keys_root, agent_id),
            "log_path": os.path.join(self._logs_root, agent_id + ".log"),
            "created_at": _utcnow_rfc3339(),
        }
        with self._lock:
            self._defs[agent_id] = definition
            self._flush()
            return dict(definition)

    def create_connected(self, name, endpoint_url, capabilities, principal_id,
                         description="", version="0.1.0", trust_tier="basic",
                         card_url=None, owner=None):
        # type: (str, str, list, str, str, str) -> dict
        """Create and persist a CONNECTED (BYO) definition — an externally
        hosted agent the runner does NOT launch; it only tracks its endpoint
        and health. Returns the stored record. ``owner`` is the principal_id
        of the USER who connected it — the only identity allowed to
        disconnect it."""
        agent_id = "agt_" + uuid.uuid4().hex[:12]
        definition = {
            "id": agent_id,
            "kind": "connected",
            "owner_principal_id": owner,
            "name": name,
            "description": description,
            "version": version,
            "template": None,
            "capabilities": list(capabilities),
            "list_price": None,
            "min_price": None,
            "endpoint_url": endpoint_url,
            # where the agent card is served (health checks use this)
            "card_url": card_url or endpoint_url,
            "principal_id": principal_id,
            # verified = agent holds its own AgentTrust identity;
            # basic = plain A2A agent, identity attested by the marketplace.
            "trust_tier": trust_tier,
            "keys_dir": None,
            "log_path": None,
            "created_at": _utcnow_rfc3339(),
        }
        with self._lock:
            self._defs[agent_id] = definition
            self._flush()
            return dict(definition)

    def get(self, agent_id):
        # type: (str) -> dict
        with self._lock:
            found = self._defs.get(agent_id)
            return dict(found) if found is not None else None

    def all(self):
        # type: () -> list
        with self._lock:
            return [dict(d) for d in self._defs.values()]

    def delete(self, agent_id):
        # type: (str) -> bool
        with self._lock:
            if agent_id not in self._defs:
                return False
            del self._defs[agent_id]
            self._flush()
            return True

    def set_owner(self, agent_id, owner):
        # type: (str, str) -> dict
        """Assign ``owner_principal_id`` (claiming an agent). Returns the
        updated record, or None if the agent doesn't exist."""
        with self._lock:
            definition = self._defs.get(agent_id)
            if definition is None:
                return None
            definition["owner_principal_id"] = owner
            self._flush()
            return dict(definition)
