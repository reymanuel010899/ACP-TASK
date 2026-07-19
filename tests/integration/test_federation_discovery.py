"""Integration tests for federation discovery (Phase B, unit U9).

Covers RFC-0004: a new app can join the ecosystem knowing only the
Registry URL — it registers itself, discovers all other apps in the same
round-trip (``ecosystem_apps``), filters apps by capability, and locates
shared services (credential vault, agent marketplace, verification) via
``GET /services?type=...``.

All servers run on EPHEMERAL ports (port=0), never fixed ports.
"""

import socket
import threading

import pytest
import requests

from apps.marketplace.server.app import make_server as make_marketplace_server
from libs.federation_client import FederationClient, FederationError
from libs.p2p_client import P2PClient
from registry.app import make_server as make_registry_server

TIMEOUT = 5.0
PING_CAPABILITY = "p2p.ping"


def _start(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def _url(server):
    host, port = server.server_address[:2]
    return "http://%s:%d" % (host, port)


def _dead_registry_url():
    """A URL nothing is listening on (ephemeral port, immediately closed)."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return "http://127.0.0.1:%d" % port


def _register_app(registry_url, app_id, endpoint, capabilities, **extra):
    payload = {
        "app_id": app_id,
        "app_endpoint": endpoint,
        "p2p_endpoint": endpoint,
        "capabilities": capabilities,
    }
    payload.update(extra)
    return requests.post(
        "%s/apps/register" % registry_url, json=payload, timeout=TIMEOUT
    )


def _register_user(registry_url, principal_id):
    resp = requests.post(
        "%s/auth/register" % registry_url,
        json={"principal_id": principal_id},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Fixtures (ephemeral ports only)
# ---------------------------------------------------------------------------


@pytest.fixture
def registry():
    server = make_registry_server(port=0)
    _start(server)
    yield _url(server)
    server.shutdown()
    server.server_close()


@pytest.fixture
def marketplace(registry):
    """Marketplace connected to the registry."""
    server = make_marketplace_server(port=0, registry_url=registry)
    _start(server)
    yield server
    server.shutdown()
    server.server_close()


# ---------------------------------------------------------------------------
# 1-2. Registration response includes the ecosystem
# ---------------------------------------------------------------------------


class TestEcosystemOnRegistration:
    def test_first_app_sees_empty_ecosystem(self, registry):
        resp = _register_app(
            registry, "app-a", "http://127.0.0.1:59990", [PING_CAPABILITY]
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["app"]["app_id"] == "app-a"
        assert body["ecosystem_apps"] == []

    def test_new_app_discovers_others_excluding_itself(self, registry):
        _register_app(
            registry, "app-a", "http://127.0.0.1:59990", [PING_CAPABILITY]
        )
        _register_app(
            registry, "app-b", "http://127.0.0.1:59991", ["b.stuff"]
        )
        resp = _register_app(
            registry, "app-c", "http://127.0.0.1:59992", ["c.stuff"]
        )
        assert resp.status_code == 200, resp.text
        ecosystem = resp.json()["ecosystem_apps"]
        ids = sorted(a["app_id"] for a in ecosystem)
        assert ids == ["app-a", "app-b"]
        # Records are full app records usable for discovery.
        assert all(a["p2p_endpoint"] for a in ecosystem)

        # Re-registration still excludes the registrant itself.
        again = _register_app(
            registry, "app-c", "http://127.0.0.1:59993", ["c.stuff"]
        )
        ids = sorted(a["app_id"] for a in again.json()["ecosystem_apps"])
        assert ids == ["app-a", "app-b"]


# ---------------------------------------------------------------------------
# 3. Capability filtering on GET /apps
# ---------------------------------------------------------------------------


class TestCapabilityFilter:
    def test_filter_by_capability(self, registry):
        _register_app(
            registry, "app-a", "http://127.0.0.1:59990",
            ["translate.text", PING_CAPABILITY],
        )
        _register_app(
            registry, "app-b", "http://127.0.0.1:59991", [PING_CAPABILITY]
        )

        resp = requests.get(
            "%s/apps" % registry,
            params={"capability": "translate.text"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
        apps = resp.json()["apps"]
        assert [a["app_id"] for a in apps] == ["app-a"]

        # Shared capability matches both.
        resp = requests.get(
            "%s/apps" % registry,
            params={"capability": PING_CAPABILITY},
            timeout=TIMEOUT,
        )
        assert sorted(
            a["app_id"] for a in resp.json()["apps"]
        ) == ["app-a", "app-b"]

        # No param -> all apps (existing U6 behavior).
        resp = requests.get("%s/apps" % registry, timeout=TIMEOUT)
        assert len(resp.json()["apps"]) == 2

    def test_unknown_capability_is_empty_list(self, registry):
        _register_app(
            registry, "app-a", "http://127.0.0.1:59990", [PING_CAPABILITY]
        )
        resp = requests.get(
            "%s/apps" % registry,
            params={"capability": "does.not.exist"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200
        assert resp.json()["apps"] == []


# ---------------------------------------------------------------------------
# 4-6. Service discovery (GET /services)
# ---------------------------------------------------------------------------


class TestServiceDiscovery:
    def test_vault_service_registration_and_lookup(self, registry):
        # A vault is a service, not an app: capabilities may be empty.
        resp = _register_app(
            registry, "vault", "http://127.0.0.1:58880", [],
            credential_vault=True,
        )
        assert resp.status_code == 200, resp.text

        resp = requests.get(
            "%s/services" % registry,
            params={"type": "credential_vault"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["service_type"] == "credential_vault"
        assert body["services"] == [
            {
                "app_id": "vault",
                "endpoint": "http://127.0.0.1:58880",
                "p2p_endpoint": "http://127.0.0.1:58880",
            }
        ]

    def test_no_services_of_type_is_empty_list(self, registry):
        resp = requests.get(
            "%s/services" % registry,
            params={"type": "agent_marketplace"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["services"] == []

    def test_bogus_service_type_is_400(self, registry):
        resp = requests.get(
            "%s/services" % registry,
            params={"type": "bogus"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 400

    def test_missing_service_type_is_400(self, registry):
        resp = requests.get("%s/services" % registry, timeout=TIMEOUT)
        assert resp.status_code == 400

    def test_app_without_flag_not_listed_as_service(self, registry):
        _register_app(
            registry, "app-a", "http://127.0.0.1:59990", [PING_CAPABILITY]
        )
        resp = requests.get(
            "%s/services" % registry,
            params={"type": "credential_vault"},
            timeout=TIMEOUT,
        )
        assert resp.json()["services"] == []


# ---------------------------------------------------------------------------
# 7-8. FederationClient: join the ecosystem knowing only the registry URL
# ---------------------------------------------------------------------------


class TestFederationClient:
    def test_join_ecosystem_discovers_apps_and_services(
        self, registry, marketplace
    ):
        marketplace_url = _url(marketplace)
        # The marketplace registers itself (as at startup).
        assert marketplace.service.register_with_registry(marketplace_url)
        # A vault service is registered (capabilities empty: service-only).
        _register_app(
            registry, "vault", "http://127.0.0.1:58881", [],
            credential_vault=True,
        )

        # app-d knows ONLY the registry URL.
        client = FederationClient(registry)
        result = client.join_ecosystem(
            "app-d", "http://127.0.0.1:57770", "http://127.0.0.1:57770",
            [PING_CAPABILITY],
        )
        ids = [a["app_id"] for a in result["ecosystem_apps"]]
        assert "marketplace" in ids
        assert "app-d" not in ids
        assert result["vault"]["app_id"] == "vault"
        assert result["vault"]["endpoint"] == "http://127.0.0.1:58881"

        # Direct service lookup works too.
        vault = client.find_service("credential_vault")
        assert vault["app_id"] == "vault"
        assert client.find_service("agent_marketplace") is None

    def test_discover_apps_with_capability_filter(self, registry):
        client = FederationClient(registry)
        client.register_app(
            "app-a", "http://127.0.0.1:59990", "http://127.0.0.1:59990",
            ["translate.text"],
        )
        client.register_app(
            "app-b", "http://127.0.0.1:59991", "http://127.0.0.1:59991",
            [PING_CAPABILITY],
        )
        assert [
            a["app_id"] for a in client.discover_apps("translate.text")
        ] == ["app-a"]
        assert len(client.discover_apps()) == 2

    def test_discovery_then_p2p_ping_end_to_end(self, registry, marketplace):
        """Proves the discovery -> P2P chain: app-d joins knowing only the
        registry URL, discovers the marketplace, then pings it directly."""
        marketplace_url = _url(marketplace)
        assert marketplace.service.register_with_registry(marketplace_url)
        _register_user(registry, "user:dana")

        client = FederationClient(registry)
        result = client.join_ecosystem(
            "app-d", "http://127.0.0.1:57770", "http://127.0.0.1:57770",
            [PING_CAPABILITY],
        )
        discovered = [
            a for a in result["ecosystem_apps"]
            if a["app_id"] == "marketplace"
        ]
        assert discovered, "marketplace not discovered via federation"
        assert discovered[0]["p2p_endpoint"] == marketplace_url

        # Now the P2P leg (RFC-0003) against the DISCOVERED app.
        response = P2PClient(registry).p2p_request(
            target_app_id="marketplace",
            requester_principal_id="user:dana",
            request_type="ping",
            capability_id=PING_CAPABILITY,
            input={},
        )
        assert response["result"]["pong"] is True
        assert response["result"]["app_id"] == "marketplace"


# ---------------------------------------------------------------------------
# 9. App startup integration (re-registration safe, U6 behavior intact)
# ---------------------------------------------------------------------------


class TestAppStartupIntegration:
    def test_marketplace_registers_and_reregistration_is_safe(
        self, registry, marketplace
    ):
        marketplace_url = _url(marketplace)
        assert marketplace.service.register_with_registry(marketplace_url)
        # Startup discovery: the app learned the ecosystem (empty here).
        assert marketplace.service.discovered_ecosystem == []

        # Registered and discoverable via U6 endpoints.
        resp = requests.get(
            "%s/apps/marketplace" % registry, timeout=TIMEOUT
        )
        assert resp.status_code == 200
        assert resp.json()["app"]["p2p_endpoint"] == marketplace_url

        # Restart-style re-registration: still exactly one entry.
        assert marketplace.service.register_with_registry(marketplace_url)
        apps = requests.get(
            "%s/apps" % registry, timeout=TIMEOUT
        ).json()["apps"]
        assert len(
            [a for a in apps if a["app_id"] == "marketplace"]
        ) == 1

    def test_startup_discovery_sees_other_apps(self, registry, marketplace):
        _register_app(
            registry, "app-a", "http://127.0.0.1:59990", [PING_CAPABILITY]
        )
        assert marketplace.service.register_with_registry(_url(marketplace))
        assert "app-a" in marketplace.service.discovered_ecosystem


# ---------------------------------------------------------------------------
# 10. Registry down: clean errors, non-fatal startup
# ---------------------------------------------------------------------------


class TestRegistryDown:
    def test_federation_client_raises_federation_error(self):
        client = FederationClient(_dead_registry_url(), timeout=1.0)
        with pytest.raises(FederationError):
            client.register_app(
                "app-x", "http://127.0.0.1:1", "http://127.0.0.1:1", []
            )
        with pytest.raises(FederationError):
            client.discover_apps()
        with pytest.raises(FederationError):
            client.find_service("credential_vault")
        with pytest.raises(FederationError):
            client.join_ecosystem(
                "app-x", "http://127.0.0.1:1", "http://127.0.0.1:1", []
            )

    def test_app_boots_when_registry_unreachable(self):
        server = make_marketplace_server(
            port=0, registry_url=_dead_registry_url()
        )
        _start(server)
        try:
            url = _url(server)
            # Startup registration is non-fatal: returns False, no raise.
            assert server.service.register_with_registry(url) is False
            # The app still serves its own (registry-independent) API.
            resp = requests.get("%s/api/tasks" % url, timeout=TIMEOUT)
            assert resp.status_code == 200, resp.text
        finally:
            server.shutdown()
            server.server_close()
