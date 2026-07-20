"""Tests for the Registry as public-key authority (Phase B.5, unit U14).

Any principal — a user (this unit) or an agent (U5) — may register a PUBLIC
key. The Registry then serves ANY principal's public key as the authority
for signature verification through a single endpoint,
``GET /principals/{principal_id}/public_key``, resolving the principal in
EITHER the user index OR the agent index.

Key custody (Decision 8): only the PUBLIC side is ever registered; the
Registry never receives private keys.

Covered scenarios:
1. Register user WITH public_key -> stored; GET returns it (200, value).
2. Register user WITHOUT public_key -> 200; GET returns 200 + null key.
3. Agent registered with public_key -> retrievable via the SAME endpoint.
4. Unknown principal (neither user nor agent) -> 404.
5. Register user with a non-string public_key -> 422.
6. Regression: register_user without a key still resolves via GET /users/{id}.
"""

import threading

import pytest
import requests

from registry.app import RegistryService, make_server
from registry.index_store import IndexStore


AGENT_CARD = {
    "name": "deploy-bot",
    "description": "Deploys infrastructure to AWS",
    "capabilities": ["aws.deploy", "terraform.apply"],
}


@pytest.fixture
def index():
    return IndexStore()


@pytest.fixture
def service(index):
    return RegistryService(index)


# ---------------------------------------------------------------------------
# Service-level (no HTTP)
# ---------------------------------------------------------------------------


class TestPublicKeyAuthority:
    def test_user_public_key_is_stored_and_served(self, service):
        """Scenario 1: user registered with public_key -> served back."""
        status, body = service.register_user(
            {
                "principal_id": "ed25519_user_alice",
                "public_key": "ed25519-pub-alice",
            }
        )
        assert status == 200, body

        status, body = service.get_principal_public_key("ed25519_user_alice")
        assert status == 200, body
        assert body["principal_id"] == "ed25519_user_alice"
        assert body["public_key"] == "ed25519-pub-alice"

    def test_user_without_public_key_serves_null(self, service):
        """Scenario 2: user registered without a key -> 200 + null key."""
        status, body = service.register_user(
            {"principal_id": "ed25519_user_bob"}
        )
        assert status == 200, body

        status, body = service.get_principal_public_key("ed25519_user_bob")
        assert status == 200, body
        assert body["principal_id"] == "ed25519_user_bob"
        assert body["public_key"] is None

    def test_agent_public_key_resolves_via_same_endpoint(self, service):
        """Scenario 3: an agent's public key resolves through the SAME
        principal endpoint (proves it resolves agents too)."""
        status, body = service.register_agent(
            {
                "agent_card": dict(AGENT_CARD),
                "principal_id": "ed25519_agent_deploybot",
                "created_by": "ed25519_user_alice",
                "public_key": "ed25519-pub-agent",
            }
        )
        assert status == 200, body

        status, body = service.get_principal_public_key(
            "ed25519_agent_deploybot"
        )
        assert status == 200, body
        assert body["principal_id"] == "ed25519_agent_deploybot"
        assert body["public_key"] == "ed25519-pub-agent"

    def test_unknown_principal_is_404(self, service):
        """Scenario 4: neither user nor agent -> 404."""
        status, body = service.get_principal_public_key("ed25519_nobody")
        assert status == 404, body
        assert "error" in body

    def test_non_string_public_key_is_422(self, service):
        """Scenario 5: a non-string public_key on registration -> 422."""
        status, body = service.register_user(
            {
                "principal_id": "ed25519_user_badkey",
                "public_key": 12345,
            }
        )
        assert status == 422, body
        assert "error" in body

    def test_regression_register_without_key_still_looks_up(self, service):
        """Scenario 6: the pre-U14 register_user flow is unchanged — a user
        registers and is still retrievable via GET /users/{id}."""
        status, body = service.register_user(
            {
                "principal_id": "ed25519_user_carol",
                "username": "carol",
            }
        )
        assert status == 200, body
        assert body["status"] == "registered"

        status, body = service.get_user("ed25519_user_carol")
        assert status == 200, body
        assert body["principal_id"] == "ed25519_user_carol"
        assert body["username"] == "carol"


# ---------------------------------------------------------------------------
# HTTP end-to-end
# ---------------------------------------------------------------------------


@pytest.fixture
def http_registry():
    server = make_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = "http://%s:%d" % server.server_address[:2]
    try:
        yield base_url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class TestPublicKeyAuthorityHTTP:
    def test_http_user_public_key_roundtrip(self, http_registry):
        resp = requests.post(
            http_registry + "/auth/register",
            json={
                "principal_id": "ed25519_user_http",
                "public_key": "ed25519-pub-http",
            },
            timeout=5,
        )
        assert resp.status_code == 200, resp.text

        resp = requests.get(
            http_registry + "/principals/ed25519_user_http/public_key",
            timeout=5,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["principal_id"] == "ed25519_user_http"
        assert body["public_key"] == "ed25519-pub-http"

    def test_http_agent_public_key_via_principals(self, http_registry):
        resp = requests.post(
            http_registry + "/agents/register",
            json={
                "agent_card": dict(AGENT_CARD),
                "principal_id": "ed25519_agent_http",
                "created_by": "ed25519_user_http",
                "public_key": "ed25519-pub-agent-http",
            },
            timeout=5,
        )
        assert resp.status_code == 200, resp.text

        resp = requests.get(
            http_registry + "/principals/ed25519_agent_http/public_key",
            timeout=5,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["public_key"] == "ed25519-pub-agent-http"

    def test_http_unknown_principal_is_404(self, http_registry):
        resp = requests.get(
            http_registry + "/principals/ed25519_ghost/public_key",
            timeout=5,
        )
        assert resp.status_code == 404, resp.text
