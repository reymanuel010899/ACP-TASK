"""Integration tests for P2P app-to-app communication (Phase B, unit U6).

Covers RFC-0003: apps register their P2P endpoints with the Registry,
requesters discover endpoints via the Registry, then talk DIRECTLY to the
target app; the target app checks permission with the Registry before
processing.

All servers run on EPHEMERAL ports (port=0), never fixed ports.
"""

import threading
import uuid

import pytest
import requests

from apps.gig_board.server.app import make_server as make_gig_board_server
from apps.marketplace.server.app import make_server as make_marketplace_server
from libs.p2p_client import AppNotFound, P2PClient, P2PPermissionDenied
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


def _register_user(registry_url, principal_id):
    resp = requests.post(
        "%s/auth/register" % registry_url,
        json={"principal_id": principal_id},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _register_app(registry_url, app_id, endpoint, capabilities,
                  p2p_endpoint=None):
    resp = requests.post(
        "%s/apps/register" % registry_url,
        json={
            "app_id": app_id,
            "app_endpoint": endpoint,
            "p2p_endpoint": p2p_endpoint or endpoint,
            "capabilities": capabilities,
        },
        timeout=TIMEOUT,
    )
    return resp


def _check_permission(registry_url, requester, target_app, capability):
    resp = requests.post(
        "%s/p2p/permissions/check" % registry_url,
        json={
            "requester_principal_id": requester,
            "target_app_id": target_app,
            "capability_id": capability,
        },
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
    yield _url(server)
    server.shutdown()
    server.server_close()


@pytest.fixture
def marketplace_standalone():
    """Marketplace with NO registry configured (standalone mode)."""
    server = make_marketplace_server(port=0, registry_url=None)
    _start(server)
    yield _url(server)
    server.shutdown()
    server.server_close()


@pytest.fixture
def gig_board_standalone():
    server = make_gig_board_server(port=0, registry_url=None)
    _start(server)
    yield _url(server)
    server.shutdown()
    server.server_close()


# ---------------------------------------------------------------------------
# 1-2. App registration with the Registry
# ---------------------------------------------------------------------------


class TestAppRegistration:
    def test_register_app_appears_in_listing(self, registry):
        resp = _register_app(
            registry, "marketplace", "http://127.0.0.1:59999",
            ["marketplace.tasks", PING_CAPABILITY],
        )
        assert resp.status_code == 200, resp.text
        app = resp.json()["app"]
        assert app["app_id"] == "marketplace"
        assert app["p2p_endpoint"] == "http://127.0.0.1:59999"
        assert app["capabilities"] == ["marketplace.tasks", PING_CAPABILITY]
        assert app["registered_at"]
        assert app["updated_at"]

        listing = requests.get("%s/apps" % registry, timeout=TIMEOUT)
        assert listing.status_code == 200
        apps = listing.json()["apps"]
        assert any(a["app_id"] == "marketplace" for a in apps)

    def test_reregistration_updates_endpoint(self, registry):
        first = _register_app(
            registry, "marketplace", "http://127.0.0.1:59998",
            [PING_CAPABILITY],
        )
        assert first.status_code == 200
        registered_at = first.json()["app"]["registered_at"]

        # Apps restart often: same app_id re-registers with a new endpoint.
        second = _register_app(
            registry, "marketplace", "http://127.0.0.1:58888",
            [PING_CAPABILITY],
        )
        assert second.status_code == 200, second.text

        got = requests.get("%s/apps/marketplace" % registry, timeout=TIMEOUT)
        assert got.status_code == 200
        app = got.json()["app"]
        assert app["p2p_endpoint"] == "http://127.0.0.1:58888"
        assert app["registered_at"] == registered_at

        # Still exactly one entry for the app_id.
        apps = requests.get("%s/apps" % registry, timeout=TIMEOUT).json()["apps"]
        assert len([a for a in apps if a["app_id"] == "marketplace"]) == 1

    def test_register_missing_fields_is_422(self, registry):
        # Missing p2p_endpoint
        resp = requests.post(
            "%s/apps/register" % registry,
            json={
                "app_id": "x",
                "app_endpoint": "http://127.0.0.1:1",
                "capabilities": [],
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 422

        # Missing app_id
        resp = requests.post(
            "%s/apps/register" % registry,
            json={
                "app_endpoint": "http://127.0.0.1:1",
                "p2p_endpoint": "http://127.0.0.1:1",
                "capabilities": [],
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 422

        # capabilities not a list of strings
        resp = requests.post(
            "%s/apps/register" % registry,
            json={
                "app_id": "x",
                "app_endpoint": "http://127.0.0.1:1",
                "p2p_endpoint": "http://127.0.0.1:1",
                "capabilities": "not-a-list",
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 3. Endpoint discovery
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_discover_app_endpoint(self, registry):
        _register_app(
            registry, "gig-board", "http://127.0.0.1:57777",
            ["gig-board.gigs"],
        )
        resp = requests.get("%s/apps/gig-board" % registry, timeout=TIMEOUT)
        assert resp.status_code == 200
        assert resp.json()["app"]["p2p_endpoint"] == "http://127.0.0.1:57777"

        client = P2PClient(registry)
        app = client.discover_app("gig-board")
        assert app["p2p_endpoint"] == "http://127.0.0.1:57777"

    def test_unknown_app_is_404(self, registry):
        resp = requests.get("%s/apps/nope" % registry, timeout=TIMEOUT)
        assert resp.status_code == 404

        with pytest.raises(AppNotFound):
            P2PClient(registry).discover_app("nope")


# ---------------------------------------------------------------------------
# 4-5. Permission checks
# ---------------------------------------------------------------------------


class TestPermissionCheck:
    def test_known_user_registered_app_supported_capability_allowed(
        self, registry
    ):
        _register_user(registry, "user:alice")
        _register_app(
            registry, "marketplace", "http://127.0.0.1:56666",
            ["marketplace.tasks", PING_CAPABILITY],
        )
        verdict = _check_permission(
            registry, "user:alice", "marketplace", PING_CAPABILITY
        )
        assert verdict["allowed"] is True

    def test_agent_principal_is_also_allowed(self, registry):
        _register_user(registry, "user:owner")
        resp = requests.post(
            "%s/agents/register" % registry,
            json={
                "principal_id": "agent:helper",
                "created_by": "user:owner",
                "agent_card": {
                    "name": "helper",
                    "description": "a helper agent",
                    "capabilities": [PING_CAPABILITY],
                },
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
        _register_app(
            registry, "marketplace", "http://127.0.0.1:56665",
            [PING_CAPABILITY],
        )
        verdict = _check_permission(
            registry, "agent:helper", "marketplace", PING_CAPABILITY
        )
        assert verdict["allowed"] is True

    def test_unknown_principal_denied_with_reason(self, registry):
        _register_app(
            registry, "marketplace", "http://127.0.0.1:56664",
            [PING_CAPABILITY],
        )
        verdict = _check_permission(
            registry, "user:ghost", "marketplace", PING_CAPABILITY
        )
        assert verdict["allowed"] is False
        assert verdict["reason"]

    def test_unsupported_capability_denied(self, registry):
        _register_user(registry, "user:bob")
        _register_app(
            registry, "marketplace", "http://127.0.0.1:56663",
            ["marketplace.tasks"],
        )
        verdict = _check_permission(
            registry, "user:bob", "marketplace", "vault.read"
        )
        assert verdict["allowed"] is False
        assert verdict["reason"]

    def test_unregistered_app_denied(self, registry):
        _register_user(registry, "user:carol")
        verdict = _check_permission(
            registry, "user:carol", "no-such-app", PING_CAPABILITY
        )
        assert verdict["allowed"] is False
        assert verdict["reason"]


# ---------------------------------------------------------------------------
# 6-7. Full P2P flow through the shared client
# ---------------------------------------------------------------------------


class TestFullP2PFlow:
    def test_ping_via_p2p_client_goes_direct_to_app(
        self, registry, marketplace
    ):
        _register_user(registry, "user:alice")
        _register_app(
            registry, "marketplace", marketplace,
            ["marketplace.tasks", PING_CAPABILITY],
        )

        client = P2PClient(registry)
        response = client.p2p_request(
            target_app_id="marketplace",
            requester_principal_id="user:alice",
            request_type="ping",
            capability_id=PING_CAPABILITY,
            input={},
        )
        assert response["result"]["pong"] is True
        assert response["result"]["app_id"] == "marketplace"
        # evidence_id must be a valid UUID
        uuid.UUID(response["evidence_id"])

        # The Registry has NO /p2p/request route: it cannot have proxied the
        # request, so the pong above proves direct app communication.
        proxied = requests.post(
            "%s/p2p/request" % registry,
            json={
                "requester_principal_id": "user:alice",
                "request_type": "ping",
                "capability_id": PING_CAPABILITY,
            },
            timeout=TIMEOUT,
        )
        assert proxied.status_code == 404

        # And the discovered endpoint is the app itself, not the registry.
        assert client.discover_app("marketplace")["p2p_endpoint"] == marketplace

    def test_permission_denied_end_to_end_is_403(
        self, registry, marketplace
    ):
        _register_app(
            registry, "marketplace", marketplace,
            ["marketplace.tasks", PING_CAPABILITY],
        )
        client = P2PClient(registry)
        with pytest.raises(P2PPermissionDenied) as excinfo:
            client.p2p_request(
                target_app_id="marketplace",
                requester_principal_id="user:nobody-registered",
                request_type="ping",
                capability_id=PING_CAPABILITY,
                input={},
            )
        assert excinfo.value.reason

        # Raw HTTP view of the same denial: the app answers 403.
        resp = requests.post(
            "%s/p2p/request" % marketplace,
            json={
                "requester_principal_id": "user:nobody-registered",
                "request_type": "ping",
                "capability_id": PING_CAPABILITY,
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 403
        body = resp.json()
        assert body["error"]
        assert body["reason"]


# ---------------------------------------------------------------------------
# 8. Standalone mode (no registry configured)
# ---------------------------------------------------------------------------


class TestStandaloneMode:
    def test_marketplace_ping_without_registry(self, marketplace_standalone):
        resp = requests.post(
            "%s/p2p/request" % marketplace_standalone,
            json={
                "requester_principal_id": "user:anyone",
                "request_type": "ping",
                "capability_id": PING_CAPABILITY,
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["result"]["pong"] is True
        assert body["result"]["app_id"] == "marketplace"
        uuid.UUID(body["evidence_id"])

    def test_gig_board_ping_without_registry(self, gig_board_standalone):
        resp = requests.post(
            "%s/p2p/request" % gig_board_standalone,
            json={
                "requester_principal_id": "user:anyone",
                "request_type": "ping",
                "capability_id": PING_CAPABILITY,
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["result"]["app_id"] == "gig-board"

    def test_unknown_request_type_is_400(self, marketplace_standalone):
        resp = requests.post(
            "%s/p2p/request" % marketplace_standalone,
            json={
                "requester_principal_id": "user:anyone",
                "request_type": "launch-missiles",
                "capability_id": PING_CAPABILITY,
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 400

    def test_missing_fields_is_422(self, marketplace_standalone):
        resp = requests.post(
            "%s/p2p/request" % marketplace_standalone,
            json={"request_type": "ping"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 9. Existing endpoints unaffected
# ---------------------------------------------------------------------------


class TestNoRegression:
    def test_marketplace_create_task_still_works(self, marketplace):
        resp = requests.post(
            "%s/api/tasks" % marketplace,
            json={
                "principal_id": "user:alice",
                "description": "translate a document",
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
        task = resp.json()["task"]
        assert task["status"] == "open"

        listing = requests.get(
            "%s/api/tasks" % marketplace, timeout=TIMEOUT
        )
        assert listing.status_code == 200
        assert listing.json()["total"] == 1
