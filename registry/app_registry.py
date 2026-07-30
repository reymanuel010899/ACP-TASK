"""App endpoint registry for direct P2P communication (Phase B, unit U6;
Postgres-backed, unit U5 database-architecture).

Unit U5 (database architecture): this module is now a thin wrapper over
:class:`registry.repository.RegistryRepository` (Postgres, ``registry``
schema, ``registry.apps`` table) -- the actual persistence logic moved to
``registry/repository.py``. ``AppRegistry`` keeps its exact pre-existing
public method signatures so ``registry/app.py`` and every existing test
needed no changes here.

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
"""

from typing import Dict, List, Optional

from registry.repository import SERVICE_TYPES, RegistryRepository

__all__ = ["SERVICE_TYPES", "AppRegistry"]


class AppRegistry(object):
    """Registered apps and their P2P endpoints (Postgres-backed, unit U5)."""

    def __init__(self, db=None):
        # type: (Optional[object]) -> None
        self._repo = RegistryRepository(db=db)

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

        ``api_key`` (a per-app secret) is accepted for signature
        compatibility but not persisted here: the prior in-memory
        implementation tracked it but nothing ever read it back.
        """
        return self._repo.register_app(
            app_id, app_endpoint, p2p_endpoint, capabilities,
            services=services,
        )

    # -- lookup ---------------------------------------------------------------

    def get_app(self, app_id):
        # type: (str) -> Optional[dict]
        """Fetch an app record (or None)."""
        return self._repo.get_app(app_id)

    def app_exists(self, app_id):
        # type: (str) -> bool
        return self._repo.app_exists(app_id)

    def list_apps(self, capability=None):
        # type: (Optional[str]) -> List[dict]
        """All registered apps, ordered by app_id.

        With ``capability`` set, only apps declaring that capability id
        (U9 capability filtering); unknown capability yields ``[]``.
        """
        return self._repo.list_apps(capability=capability)

    def find_services(self, service_type):
        # type: (str) -> List[dict]
        """Apps/services advertising ``service_type`` (U9, RFC-0004).

        Returns full records, ordered by app_id; empty list when nobody
        provides the service. Unknown types simply match nothing —
        HTTP-level validation (400 for a bogus type) lives upstream.
        """
        return self._repo.find_services(service_type)
