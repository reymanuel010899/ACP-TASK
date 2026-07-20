"""App endpoint registry for direct P2P communication (Phase B, unit U6).

The Registry acts as a signaling hub in a star topology (RFC-0003): apps
register their HTTP endpoints here, requesters discover an app's
``p2p_endpoint`` through the Registry, then talk to the app DIRECTLY —
the Registry never proxies P2P traffic.

U9 (federation discovery, RFC-0004) extends the U6 register/lookup surface:
registrations may advertise shared **service types** (agent marketplace,
credential vault, verification service) via boolean flags, capability
filtering is supported on listing, and ``find_services`` answers "who
provides service X?". A standalone service (e.g. the vault) registers with
an empty ``capabilities`` list — services are directory entries too.

Thread-safe (a single lock guards all mutation) so it can back the
``ThreadingHTTPServer`` in ``registry.app``.
"""

import datetime
import threading

from typing import Dict, List, Optional

#: Service types the federation layer knows how to look up (RFC-0004).
SERVICE_TYPES = (
    "agent_marketplace",
    "credential_vault",
    "verification_service",
)


def _utcnow_rfc3339():
    # type: () -> str
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


class AppRegistry(object):
    """Registered apps and their P2P endpoints."""

    def __init__(self):
        # type: () -> None
        self._lock = threading.RLock()
        # app_id -> app record (public fields only)
        self._apps = {}  # type: Dict[str, dict]
        # app_id -> api_key (never serialized into public records)
        self._api_keys = {}  # type: Dict[str, str]

    # -- registration ---------------------------------------------------------

    def register_app(
        self, app_id, app_endpoint, p2p_endpoint, capabilities, api_key=None,
        services=None,
    ):
        # type: (str, str, str, List[str], Optional[str], Optional[Dict[str, bool]]) -> dict
        """Register (or re-register) an app; return the stored record.

        Apps restart often, so a duplicate ``app_id`` is NOT an error:
        re-registration updates the endpoints/capabilities in place while
        preserving the original ``registered_at`` (and bumping
        ``updated_at``). Assumes validation happened upstream
        (``RegistryService``).

        ``services`` (U9) maps service types (:data:`SERVICE_TYPES`) to
        booleans; omitted flags default to False. A standalone service (a
        vault is not an "app" with capabilities) registers with
        ``capabilities=[]`` and the relevant flag set.
        """
        now = _utcnow_rfc3339()
        flags = services or {}
        with self._lock:
            existing = self._apps.get(app_id)
            record = {
                "app_id": app_id,
                "app_endpoint": app_endpoint,
                "p2p_endpoint": p2p_endpoint,
                "capabilities": list(capabilities),
                "services": {
                    service_type: bool(flags.get(service_type, False))
                    for service_type in SERVICE_TYPES
                },
                "registered_at": (
                    existing["registered_at"] if existing else now
                ),
                "updated_at": now,
            }
            self._apps[app_id] = record
            if api_key is not None:
                self._api_keys[app_id] = api_key
            return _copy_record(record)

    # -- lookup ---------------------------------------------------------------

    def get_app(self, app_id):
        # type: (str) -> Optional[dict]
        """Fetch an app record (or None)."""
        with self._lock:
            record = self._apps.get(app_id)
            return _copy_record(record) if record is not None else None

    def app_exists(self, app_id):
        # type: (str) -> bool
        with self._lock:
            return app_id in self._apps

    def list_apps(self, capability=None):
        # type: (Optional[str]) -> List[dict]
        """All registered apps, ordered by app_id.

        With ``capability`` set, only apps declaring that capability id
        (U9 capability filtering); unknown capability yields ``[]``.
        """
        with self._lock:
            return [
                _copy_record(self._apps[app_id])
                for app_id in sorted(self._apps)
                if capability is None
                or capability in self._apps[app_id]["capabilities"]
            ]

    def find_services(self, service_type):
        # type: (str) -> List[dict]
        """Apps/services advertising ``service_type`` (U9, RFC-0004).

        Returns full records, ordered by app_id; empty list when nobody
        provides the service. Unknown types simply match nothing —
        HTTP-level validation (400 for a bogus type) lives upstream.
        """
        with self._lock:
            return [
                _copy_record(self._apps[app_id])
                for app_id in sorted(self._apps)
                if self._apps[app_id]["services"].get(service_type, False)
            ]


def _copy_record(record):
    # type: (dict) -> dict
    """Copy a record so callers cannot mutate stored state (the nested
    ``services`` dict included)."""
    copied = dict(record)
    copied["capabilities"] = list(record["capabilities"])
    copied["services"] = dict(record["services"])
    return copied
