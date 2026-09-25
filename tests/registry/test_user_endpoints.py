"""Tests for user-level reputation in the AgentTrust Reference Registry (unit U1).

This test suite covers the new user-level reputation features that complement
the existing agent registry. Users (principals) can:
- Register with their Principal ed25519 key
- Log in to retrieve their current reputation
- Query their reputation records
- Have reputation recorded by the verification service

Covered scenarios:
- Happy path: user registration, login, reputation query
- Edge cases: duplicate registration, invalid principals, missing fields
- Integration: reputation updates flow to users
- HTTP end-to-end: registration, login, reputation query through HTTP
"""

import json
import threading
import pytest
import requests

from registry.app import RegistryService, make_server
from registry.index_store import IndexStore


@pytest.fixture
def index():
    return IndexStore()


@pytest.fixture
def service(index):
    return RegistryService(index)


# ---------------------------------------------------------------------------
# Happy path: user registration, login, and queries
# ---------------------------------------------------------------------------


class TestUserRegistration:
    def test_registration_assigns_the_configured_home_organization(self, index):
        class Users:
            def __init__(self):
                self.created = None

            def user_exists(self, _principal_id):
                return False

            def create_user(self, principal_id, **values):
                self.created = (principal_id, values)
                return {"principal_id": principal_id}

            def get_aggregated_reputation(self, _principal_id):
                return {
                    "tasks_verified": 0, "tasks_rejected": 0,
                    "verification_rate": None,
                }

        users = Users()
        service = RegistryService(
            index, user_index=users,
            default_organization_id="org:local",
        )

        status, _body = service.register_user({
            "principal_id": "principal:new", "username": "new-user",
        })

        assert status == 200
        assert users.created == ("principal:new", {
            "username": "new-user",
            "public_key": None,
            "home_organization_id": "org:local",
        })

    def test_register_new_user_with_principal(self, service):
        """User registration returns 200 with principal_id stored."""
        status, body = service.register_user(
            {
                "principal_id": "ed25519_user_alice",
                "username": "alice",
            }
        )
        assert status == 200, body
        assert body["status"] == "registered"
        assert body["principal_id"] == "ed25519_user_alice"
        assert "reputation" in body
        # New user has neutral reputation
        assert body["reputation"]["tasks_verified"] == 0
        assert body["reputation"]["tasks_rejected"] == 0
        assert body["reputation"]["verification_rate"] is None

    def test_register_user_without_username(self, service):
        """User registration works without optional username."""
        status, body = service.register_user(
            {"principal_id": "ed25519_user_bob"}
        )
        assert status == 200, body
        assert body["principal_id"] == "ed25519_user_bob"

    def test_register_duplicate_principal_is_409(self, service):
        """Registering the same principal twice returns 409 (conflict)."""
        service.register_user({"principal_id": "ed25519_user_charlie"})
        status, body = service.register_user(
            {"principal_id": "ed25519_user_charlie"}
        )
        assert status == 409, body
        assert "error" in body

    def test_register_missing_principal_id_is_422(self, service):
        """Missing principal_id returns 422 (validation error)."""
        status, body = service.register_user({})
        assert status == 422, body
        assert "error" in body

    def test_register_empty_principal_id_is_422(self, service):
        """Empty principal_id returns 422."""
        status, body = service.register_user({"principal_id": ""})
        assert status == 422, body
        assert "error" in body

    def test_register_non_string_principal_is_422(self, service):
        """Non-string principal_id returns 422."""
        status, body = service.register_user({"principal_id": 123})
        assert status == 422, body
        assert "error" in body

    def test_register_invalid_payload_is_422(self, service):
        """Invalid payload (not a dict) returns 422."""
        status, body = service.register_user("invalid")
        assert status == 422, body
        assert "error" in body


class TestUserLogin:
    def test_login_existing_user(self, service):
        """Login with valid principal returns user's current reputation."""
        # Register user first
        service.register_user({"principal_id": "ed25519_user_diana"})

        # Login
        status, body = service.login_user(
            {"principal_id": "ed25519_user_diana"}
        )
        assert status == 200, body
        assert body["status"] == "ok"
        assert body["principal_id"] == "ed25519_user_diana"
        assert "reputation" in body

    def test_login_nonexistent_user_is_404(self, service):
        """Login with non-existent principal returns 404."""
        status, body = service.login_user(
            {"principal_id": "ed25519_user_nobody"}
        )
        assert status == 404, body
        assert "error" in body

    def test_login_missing_principal_is_422(self, service):
        """Login without principal_id returns 422."""
        status, body = service.login_user({})
        assert status == 422, body
        assert "error" in body

    def test_login_empty_principal_is_422(self, service):
        """Login with empty principal_id returns 422."""
        status, body = service.login_user({"principal_id": ""})
        assert status == 422, body

    def test_login_non_string_principal_is_422(self, service):
        """Login with non-string principal_id returns 422."""
        status, body = service.login_user({"principal_id": 456})
        assert status == 422, body

    def test_resolve_username_returns_principal(self, service):
        service.user_index.find_users_by_username = lambda username: [
            {"principal_id": "ed25519_user_resolved"}
        ] if username == "resolved-user" else []

        status, body = service.resolve_username("resolved-user")

        assert status == 200
        assert body == {
            "username": "resolved-user",
            "principal_id": "ed25519_user_resolved",
        }

    def test_resolve_username_handles_missing_and_ambiguous_names(self, service):
        service.user_index.find_users_by_username = lambda _username: []
        assert service.resolve_username("missing")[0] == 404

        service.user_index.find_users_by_username = lambda _username: [
            {"principal_id": "one"},
            {"principal_id": "two"},
        ]
        assert service.resolve_username("duplicate")[0] == 409


class TestUserReputationQuery:
    def test_get_user_reputation(self, service):
        """Query user reputation returns their record and history."""
        service.register_user({"principal_id": "ed25519_user_eve"})

        status, body = service.get_user("ed25519_user_eve")
        assert status == 200, body
        assert body["principal_id"] == "ed25519_user_eve"
        assert "reputation_records" in body
        assert isinstance(body["reputation_records"], list)
        assert "created_at" in body
        assert "last_active" in body

    def test_get_nonexistent_user_is_404(self, service):
        """Query non-existent user returns 404."""
        status, body = service.get_user("ed25519_user_nobody")
        assert status == 404, body
        assert "error" in body

    def test_get_user_empty_principal_is_422(self, service):
        """Query with empty principal returns 422."""
        status, body = service.get_user("")
        assert status == 422, body


class TestUserReputationUpdate:
    def test_record_user_reputation(self, service):
        """Recording reputation for user stores and aggregates."""
        service.register_user({"principal_id": "ed25519_user_frank"})

        # Add a verified task
        status, body = service.update_user_reputation(
            "ed25519_user_frank",
            {
                "task_id": "task-1",
                "verified": True,
                "capability_id": "code.review",
            },
        )
        assert status == 200, body
        assert body["verified"] is True
        assert "reputation_summary" in body
        assert body["reputation_summary"]["tasks_verified"] == 1
        assert body["reputation_summary"]["tasks_rejected"] == 0
        assert body["reputation_summary"]["verification_rate"] == 1.0

    def test_record_rejected_reputation(self, service):
        """Recording rejected task updates counts."""
        service.register_user({"principal_id": "ed25519_user_grace"})

        status, body = service.update_user_reputation(
            "ed25519_user_grace",
            {
                "task_id": "task-2",
                "verified": False,
                "capability_id": "terraform.generate",
            },
        )
        assert status == 200, body
        assert body["verified"] is False
        summary = body["reputation_summary"]
        assert summary["tasks_verified"] == 0
        assert summary["tasks_rejected"] == 1
        assert summary["verification_rate"] == 0.0

    def test_multiple_reputation_records_aggregate(self, service):
        """Multiple reputation records are aggregated correctly."""
        service.register_user({"principal_id": "ed25519_user_helen"})

        # Verified
        service.update_user_reputation(
            "ed25519_user_helen",
            {
                "task_id": "task-3",
                "verified": True,
                "capability_id": "code.review",
            },
        )
        # Verified
        service.update_user_reputation(
            "ed25519_user_helen",
            {
                "task_id": "task-4",
                "verified": True,
                "capability_id": "code.review",
            },
        )
        # Rejected
        service.update_user_reputation(
            "ed25519_user_helen",
            {
                "task_id": "task-5",
                "verified": False,
                "capability_id": "code.review",
            },
        )

        status, body = service.get_user("ed25519_user_helen")
        assert status == 200
        records = body["reputation_records"]
        assert len(records) > 0
        # Find the aggregated record for code.review
        code_review_record = next(
            (r for r in records if r["capability_id"] == "code.review"),
            None,
        )
        assert code_review_record is not None
        assert code_review_record["tasks_verified"] == 2
        assert code_review_record["tasks_rejected"] == 1
        # Unit U5 (database architecture): verification_rate is now a
        # Postgres GENERATED column, `round(verified / total, 4)` (verbatim
        # design-doc DDL, migrations/0006_trust.sql) rather than an
        # unrounded Python float division -- 2/3 stores as 0.6667, not
        # 0.6666666666666666. The default pytest.approx tolerance (relative
        # 1e-6) is tighter than that intentional 4-decimal rounding, so this
        # needs an explicit absolute tolerance wide enough to accept it.
        assert code_review_record["verification_rate"] == pytest.approx(
            2.0 / 3, abs=1e-4
        )

    def test_update_reputation_for_nonexistent_user_is_404(self, service):
        """Updating reputation for non-existent user returns 404."""
        status, body = service.update_user_reputation(
            "ed25519_user_nobody",
            {"task_id": "task-x", "verified": True, "capability_id": "any"},
        )
        assert status == 404, body

    def test_update_reputation_missing_fields_is_422(self, service):
        """Update without required fields returns 422."""
        service.register_user({"principal_id": "ed25519_user_iris"})

        # Missing 'verified'
        status, body = service.update_user_reputation(
            "ed25519_user_iris",
            {"task_id": "task-y", "capability_id": "any"},
        )
        assert status == 422, body

        # Missing 'capability_id'
        status, body = service.update_user_reputation(
            "ed25519_user_iris",
            {"task_id": "task-y", "verified": True},
        )
        assert status == 422, body


# ---------------------------------------------------------------------------
# HTTP end-to-end: register, login, query through HTTP
# ---------------------------------------------------------------------------


@pytest.fixture
def http_registry():
    """HTTP registry server for testing."""
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


class TestUserHTTPEndToEnd:
    def test_http_register_user(self, http_registry):
        """HTTP POST /auth/register registers a user."""
        resp = requests.post(
            http_registry + "/auth/register",
            json={"principal_id": "ed25519_user_jack", "username": "jack"},
            timeout=5,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "registered"
        assert body["principal_id"] == "ed25519_user_jack"

    def test_http_register_duplicate_is_409(self, http_registry):
        """HTTP duplicate registration returns 409."""
        requests.post(
            http_registry + "/auth/register",
            json={"principal_id": "ed25519_user_kate"},
            timeout=5,
        )
        resp = requests.post(
            http_registry + "/auth/register",
            json={"principal_id": "ed25519_user_kate"},
            timeout=5,
        )
        assert resp.status_code == 409

    def test_http_login_user(self, http_registry):
        """HTTP POST /auth/login logs in a user."""
        requests.post(
            http_registry + "/auth/register",
            json={"principal_id": "ed25519_user_leo"},
            timeout=5,
        )
        resp = requests.post(
            http_registry + "/auth/login",
            json={"principal_id": "ed25519_user_leo"},
            timeout=5,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["principal_id"] == "ed25519_user_leo"

    def test_http_login_nonexistent_is_404(self, http_registry):
        """HTTP login for non-existent user returns 404."""
        resp = requests.post(
            http_registry + "/auth/login",
            json={"principal_id": "ed25519_user_nobody"},
            timeout=5,
        )
        assert resp.status_code == 404

    def test_http_get_user_reputation(self, http_registry):
        """HTTP GET /users/{principal_id} retrieves user reputation."""
        requests.post(
            http_registry + "/auth/register",
            json={"principal_id": "ed25519_user_mike"},
            timeout=5,
        )
        resp = requests.get(
            http_registry + "/users/ed25519_user_mike",
            timeout=5,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["principal_id"] == "ed25519_user_mike"
        assert "reputation_records" in body

    def test_http_get_nonexistent_user_is_404(self, http_registry):
        """HTTP GET for non-existent user returns 404."""
        resp = requests.get(
            http_registry + "/users/ed25519_user_nobody",
            timeout=5,
        )
        assert resp.status_code == 404

    def test_http_update_user_reputation(self, http_registry):
        """HTTP POST /users/{principal_id}/reputation records reputation."""
        requests.post(
            http_registry + "/auth/register",
            json={"principal_id": "ed25519_user_nancy"},
            timeout=5,
        )
        resp = requests.post(
            http_registry + "/users/ed25519_user_nancy/reputation",
            json={
                "task_id": "task-http-1",
                "verified": True,
                "capability_id": "code.review",
            },
            timeout=5,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["verified"] is True
        assert body["reputation_summary"]["tasks_verified"] == 1

    def test_http_update_reputation_for_nonexistent_is_404(self, http_registry):
        """HTTP reputation update for non-existent user returns 404."""
        resp = requests.post(
            http_registry + "/users/ed25519_user_nobody/reputation",
            json={
                "task_id": "task-x",
                "verified": True,
                "capability_id": "any",
            },
            timeout=5,
        )
        assert resp.status_code == 404

    def test_http_malformed_json_is_400(self, http_registry):
        """HTTP malformed JSON returns 400."""
        resp = requests.post(
            http_registry + "/auth/register",
            data="not json",
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
        assert resp.status_code == 400

    def test_http_missing_field_is_422(self, http_registry):
        """HTTP request with missing required field returns 422."""
        resp = requests.post(
            http_registry + "/auth/register",
            json={"username": "missing_principal"},
            timeout=5,
        )
        assert resp.status_code == 422

    def test_http_user_principal_url_encoding(self, http_registry):
        """HTTP URL-encoded principal_id in path."""
        principal_id = "ed25519_user:oscar"
        requests.post(
            http_registry + "/auth/register",
            json={"principal_id": principal_id},
            timeout=5,
        )
        # URL-encode the colon
        encoded = principal_id.replace(":", "%3A")
        resp = requests.get(
            http_registry + f"/users/{encoded}",
            timeout=5,
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Backward compatibility: existing agent endpoints still work
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_agent_search_still_works(self, service, http_registry):
        """Existing agent search endpoint still works."""
        # This test verifies /search still works
        resp = requests.get(
            http_registry + "/search",
            params={"capability": "any.capability"},
            timeout=5,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "candidates" in body

    def test_agent_endpoints_unaffected_by_user_routes(self, service):
        """User routes don't interfere with agent routes."""
        # Register a user
        service.register_user({"principal_id": "ed25519_user_paul"})

        # Agent endpoints should still work (we can't easily test this without
        # an agent registration, but we verify the service still has the method)
        assert hasattr(service, "register")
        assert hasattr(service, "search")
        assert hasattr(service, "get_agent")
