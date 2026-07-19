"""Tests for web console user auth endpoints (unit U2).

Tests the user registration and login flow:
- User registers with Principal -> stored in registry
- User logs in with valid Principal -> session created
- User logs in with invalid Principal -> 401
- User views reputation -> sees their stats
- Session persists across page reloads (via localStorage, tested client-side)
"""

import json
import threading

import pytest
import requests

from web.app import make_server


def base_url(server):
    host, port = server.server_address[:2]
    return "http://%s:%d" % (host, port)


@pytest.fixture
def console(tmp_path):
    server = make_server(port=0, keys_root=str(tmp_path / "keys"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.stack.shutdown()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class TestUserAuth:
    """User authentication endpoints."""

    def test_register_new_principal(self, console):
        """User can register with a new Principal."""
        principal_id = "AwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="  # sample base64
        resp = requests.post(
            base_url(console) + "/api/auth/register",
            json={"principal_id": principal_id},
            timeout=5,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "registered"
        assert body["principal_id"] == principal_id

    def test_register_duplicate_principal_fails(self, console):
        """Registering the same Principal twice returns 409."""
        principal_id = "AwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
        # First registration succeeds
        resp1 = requests.post(
            base_url(console) + "/api/auth/register",
            json={"principal_id": principal_id},
            timeout=5,
        )
        assert resp1.status_code == 200

        # Second registration with same Principal fails
        resp2 = requests.post(
            base_url(console) + "/api/auth/register",
            json={"principal_id": principal_id},
            timeout=5,
        )
        assert resp2.status_code == 409, resp2.text
        assert "already registered" in resp2.json().get("error", "").lower()

    def test_register_empty_principal_fails(self, console):
        """Registering with empty principal_id returns 400."""
        resp = requests.post(
            base_url(console) + "/api/auth/register",
            json={"principal_id": ""},
            timeout=5,
        )
        assert resp.status_code == 400
        assert "principal_id" in resp.json().get("error", "").lower()

    def test_login_existing_principal(self, console):
        """User can log in with a registered Principal."""
        principal_id = "AwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
        # Register first
        requests.post(
            base_url(console) + "/api/auth/register",
            json={"principal_id": principal_id},
            timeout=5,
        )
        # Then log in
        resp = requests.post(
            base_url(console) + "/api/auth/login",
            json={"principal_id": principal_id},
            timeout=5,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "ok"
        assert body["principal_id"] == principal_id

    def test_login_nonexistent_principal_fails(self, console):
        """Logging in with unregistered Principal returns 404."""
        principal_id = "NotRegisteredPrincipalID=="
        resp = requests.post(
            base_url(console) + "/api/auth/login",
            json={"principal_id": principal_id},
            timeout=5,
        )
        assert resp.status_code == 404
        assert "not found" in resp.json().get("error", "").lower()

    def test_login_empty_principal_fails(self, console):
        """Logging in with empty principal_id returns 400."""
        resp = requests.post(
            base_url(console) + "/api/auth/login",
            json={"principal_id": ""},
            timeout=5,
        )
        assert resp.status_code == 400
        assert "principal_id" in resp.json().get("error", "").lower()

    def test_get_reputation_after_registration(self, console):
        """User can fetch their reputation after registration."""
        principal_id = "AwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
        # Register
        requests.post(
            base_url(console) + "/api/auth/register",
            json={"principal_id": principal_id},
            timeout=5,
        )
        # Fetch reputation
        resp = requests.get(
            base_url(console) + "/api/reputation/" + principal_id,
            timeout=5,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["principal_id"] == principal_id
        # New users have no reputation records
        reputation_records = body.get("reputation_records", [])
        assert isinstance(reputation_records, list)

    def test_get_reputation_nonexistent_principal_fails(self, console):
        """Fetching reputation for unregistered Principal returns 404."""
        resp = requests.get(
            base_url(console) + "/api/reputation/NotRegisteredPrincipalID==",
            timeout=5,
        )
        assert resp.status_code == 404

    def test_registration_includes_reputation_data(self, console):
        """Registration response includes reputation info."""
        principal_id = "AwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
        resp = requests.post(
            base_url(console) + "/api/auth/register",
            json={"principal_id": principal_id},
            timeout=5,
        )
        assert resp.status_code == 200
        body = resp.json()
        # Should include reputation summary
        reputation = body.get("reputation")
        assert isinstance(reputation, dict)
        assert "tasks_verified" in reputation
        assert "tasks_rejected" in reputation
        assert reputation["tasks_verified"] == 0
        assert reputation["tasks_rejected"] == 0

    def test_login_includes_reputation_data(self, console):
        """Login response includes reputation info."""
        principal_id = "AwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
        # Register first
        requests.post(
            base_url(console) + "/api/auth/register",
            json={"principal_id": principal_id},
            timeout=5,
        )
        # Log in
        resp = requests.post(
            base_url(console) + "/api/auth/login",
            json={"principal_id": principal_id},
            timeout=5,
        )
        assert resp.status_code == 200
        body = resp.json()
        # Should include reputation summary
        reputation = body.get("reputation")
        assert isinstance(reputation, dict)
        assert "tasks_verified" in reputation
        assert "tasks_rejected" in reputation

    def test_session_endpoint_exists(self, console):
        """GET /api/auth/session returns ok."""
        resp = requests.get(
            base_url(console) + "/api/auth/session",
            timeout=5,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body


class TestUserAuthIntegration:
    """End-to-end user auth flows."""

    def test_full_register_login_flow(self, console):
        """Complete flow: register -> login -> view reputation."""
        principal_id = "AwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="

        # Step 1: Register
        reg_resp = requests.post(
            base_url(console) + "/api/auth/register",
            json={"principal_id": principal_id},
            timeout=5,
        )
        assert reg_resp.status_code == 200

        # Step 2: Log in
        login_resp = requests.post(
            base_url(console) + "/api/auth/login",
            json={"principal_id": principal_id},
            timeout=5,
        )
        assert login_resp.status_code == 200
        assert login_resp.json()["principal_id"] == principal_id

        # Step 3: View reputation
        rep_resp = requests.get(
            base_url(console) + "/api/reputation/" + principal_id,
            timeout=5,
        )
        assert rep_resp.status_code == 200
        assert rep_resp.json()["principal_id"] == principal_id

    def test_multiple_users_independent_reputation(self, console):
        """Multiple users have independent reputation."""
        user1 = "User1PrincipalIDBase64AAAAAAAAAAAAAAAAAA=="
        user2 = "User2PrincipalIDBase64AAAAAAAAAAAAAAAAAA=="

        # Register both
        requests.post(
            base_url(console) + "/api/auth/register",
            json={"principal_id": user1},
            timeout=5,
        )
        requests.post(
            base_url(console) + "/api/auth/register",
            json={"principal_id": user2},
            timeout=5,
        )

        # Fetch reputation for each
        rep1 = requests.get(
            base_url(console) + "/api/reputation/" + user1,
            timeout=5,
        ).json()
        rep2 = requests.get(
            base_url(console) + "/api/reputation/" + user2,
            timeout=5,
        ).json()

        assert rep1["principal_id"] == user1
        assert rep2["principal_id"] == user2
        # Both should have neutral reputation
        assert rep1["reputation_records"] == []
        assert rep2["reputation_records"] == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
