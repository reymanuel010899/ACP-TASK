"""Federation discovery client (Phase B, unit U9, RFC-0004).

A new app can join the AgentTrust ecosystem knowing ONLY the Registry URL:
it registers itself, discovers every other app in the same round-trip
(``ecosystem_apps``), and locates shared services (credential vault, agent
marketplace, verification service) by type.

Usage::

    from libs.federation_client import FederationClient

    client = FederationClient("http://127.0.0.1:8090")
    joined = client.join_ecosystem(
        "my-app", "http://127.0.0.1:8005", "http://127.0.0.1:8005",
        ["my-app.things", "p2p.ping"],
    )
    # joined == {"ecosystem_apps": [...], "vault": {...} | None,
    #            "agent_marketplace": {...} | None}

All failures (registry unreachable, non-2xx answers, malformed bodies)
raise :class:`FederationError` — callers that must tolerate a down
registry (app startup) catch it and continue.
"""

from typing import List, Optional

import requests

DEFAULT_TIMEOUT = 5.0

#: Service types the Registry knows how to look up (mirrors
#: ``registry.app_registry.SERVICE_TYPES``; kept literal so this client
#: stays importable without the registry package installed).
SERVICE_TYPES = (
    "agent_marketplace",
    "credential_vault",
    "verification_service",
)


class FederationError(Exception):
    """Registry unreachable, rejected the request, or answered garbage."""


class FederationClient(object):
    """Register with and discover the ecosystem through one Registry."""

    def __init__(self, registry_url, timeout=DEFAULT_TIMEOUT):
        # type: (str, float) -> None
        if not registry_url:
            raise ValueError("registry_url is required")
        self.registry_url = registry_url.rstrip("/")
        self.timeout = timeout

    # -- registration ---------------------------------------------------------

    def register_app(
        self, app_id, app_endpoint, p2p_endpoint, capabilities,
        **service_flags
    ):
        # type: (str, str, str, List[str], bool) -> dict
        """``POST /apps/register`` — register (or re-register) this app.

        ``service_flags`` are the optional booleans of RFC-0004
        (``credential_vault=True`` etc.). ``capabilities`` may be an empty
        list for service-only registrations. Returns the response body:
        ``{"app": ..., "ecosystem_apps": [...]}`` — every OTHER registered
        app, so joining and discovering is one round-trip.
        """
        payload = {
            "app_id": app_id,
            "app_endpoint": app_endpoint,
            "p2p_endpoint": p2p_endpoint,
            "capabilities": list(capabilities),
        }
        payload.update(service_flags)
        body = self._request(
            "POST", "/apps/register", json=payload,
            context="app registration",
        )
        if not isinstance(body.get("app"), dict):
            raise FederationError(
                "registry returned a malformed registration response"
            )
        body.setdefault("ecosystem_apps", [])
        return body

    # -- discovery ------------------------------------------------------------

    def discover_apps(self, capability=None):
        # type: (Optional[str]) -> List[dict]
        """``GET /apps[?capability=...]`` — registered apps, optionally
        filtered by capability id (unknown capability → ``[]``)."""
        params = {"capability": capability} if capability else None
        body = self._request(
            "GET", "/apps", params=params, context="app discovery"
        )
        apps = body.get("apps")
        if not isinstance(apps, list):
            raise FederationError("registry returned a malformed app list")
        return apps

    def find_service(self, service_type):
        # type: (str) -> Optional[dict]
        """``GET /services?type=...`` — first provider of ``service_type``
        as ``{app_id, endpoint, p2p_endpoint}``, or None when nobody
        provides it. Unknown types raise :class:`FederationError` (the
        Registry answers 400)."""
        body = self._request(
            "GET", "/services", params={"type": service_type},
            context="service lookup",
        )
        services = body.get("services")
        if not isinstance(services, list):
            raise FederationError(
                "registry returned a malformed service list"
            )
        return services[0] if services else None

    # -- one-call join --------------------------------------------------------

    def join_ecosystem(
        self, app_id, app_endpoint, p2p_endpoint, capabilities=None,
        **service_flags
    ):
        # type: (str, str, str, Optional[List[str]], bool) -> dict
        """Register and discover in one call (RFC-0004 §join).

        Returns ``{"ecosystem_apps": [...], "vault": ... | None,
        "agent_marketplace": ... | None}`` — everything a new app needs to
        start participating, knowing only the Registry URL.
        """
        registration = self.register_app(
            app_id, app_endpoint, p2p_endpoint, capabilities or [],
            **service_flags
        )
        return {
            "ecosystem_apps": registration["ecosystem_apps"],
            "vault": self.find_service("credential_vault"),
            "agent_marketplace": self.find_service("agent_marketplace"),
        }

    # -- helpers --------------------------------------------------------------

    def _request(self, method, path, json=None, params=None, context=""):
        # type: (str, str, Optional[dict], Optional[dict], str) -> dict
        """One Registry round-trip; every failure mode is a clean
        :class:`FederationError` (never a raw requests exception)."""
        url = self.registry_url + path
        try:
            resp = requests.request(
                method, url, json=json, params=params, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise FederationError(
                "registry unreachable for %s (%s): %s" % (context, url, exc)
            )
        if resp.status_code != 200:
            raise FederationError(
                "%s failed (%d): %s" % (context, resp.status_code, resp.text)
            )
        try:
            body = resp.json()
        except ValueError:
            raise FederationError(
                "registry response for %s is not valid JSON" % context
            )
        if not isinstance(body, dict):
            raise FederationError(
                "registry response for %s is not a JSON object" % context
            )
        return body
