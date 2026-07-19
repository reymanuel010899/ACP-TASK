"""App endpoint registry for direct P2P communication (Phase B, unit U6).

The Registry acts as a signaling hub in a star topology (RFC-0003): apps
register their HTTP endpoints here, requesters discover an app's
``p2p_endpoint`` through the Registry, then talk to the app DIRECTLY —
the Registry never proxies P2P traffic.

Scope note: this is the minimal registry P2P needs — register an app with
its endpoints and look it up. U9 (federation discovery) will extend it with
service-type discovery and capability manifests; the record shape is kept
open (a plain dict) so those fields can be added without migration.

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
        self, app_id, app_endpoint, p2p_endpoint, capabilities, api_key=None
    ):
        # type: (str, str, str, List[str], Optional[str]) -> dict
        """Register (or re-register) an app; return the stored record.

        Apps restart often, so a duplicate ``app_id`` is NOT an error:
        re-registration updates the endpoints/capabilities in place while
        preserving the original ``registered_at`` (and bumping
        ``updated_at``). Assumes validation happened upstream
        (``RegistryService``).
        """
        now = _utcnow_rfc3339()
        with self._lock:
            existing = self._apps.get(app_id)
            record = {
                "app_id": app_id,
                "app_endpoint": app_endpoint,
                "p2p_endpoint": p2p_endpoint,
                "capabilities": list(capabilities),
                "registered_at": (
                    existing["registered_at"] if existing else now
                ),
                "updated_at": now,
            }
            self._apps[app_id] = record
            if api_key is not None:
                self._api_keys[app_id] = api_key
            return dict(record)

    # -- lookup ---------------------------------------------------------------

    def get_app(self, app_id):
        # type: (str) -> Optional[dict]
        """Fetch an app record (or None)."""
        with self._lock:
            record = self._apps.get(app_id)
            return dict(record) if record is not None else None

    def app_exists(self, app_id):
        # type: (str) -> bool
        with self._lock:
            return app_id in self._apps

    def list_apps(self):
        # type: () -> List[dict]
        """All registered apps, ordered by app_id."""
        with self._lock:
            return [
                dict(self._apps[app_id]) for app_id in sorted(self._apps)
            ]
