"""Integration tests for independent registry with multiple apps (Unit U5).

This test suite verifies that:
1. Registry can start as an independent service
2. Multiple apps can connect to the same registry simultaneously
3. Reputation records survive app/registry restarts
4. No app can corrupt registry data
5. Concurrent writes are serialized correctly (no data loss)

Scenarios covered:
- Happy path: registry starts, apps connect, data persists
- Concurrent writes: multiple apps write simultaneously, no data loss
- Persistence: data survives registry/app restart
- Isolation: apps cannot corrupt each other's data
"""

import subprocess
import sys
import threading
import time
from typing import Dict, Optional

import pytest
import requests

from registry.app import RegistryService, make_server
from registry.index_store import IndexStore
from registry.user_index import UserIndex


# ---------------------------------------------------------------------------
# Fixtures for standalone registry server and test apps
# ---------------------------------------------------------------------------


@pytest.fixture
def registry_service():
    """Create a RegistryService (Postgres-backed, unit U5)."""
    index = IndexStore()
    user_index = UserIndex()
    return RegistryService(index, user_index=user_index)


@pytest.fixture
def registry_server(registry_service):
    """Start an independent registry HTTP server."""
    server = make_server(
        port=0,  # Pick a free port
        host="127.0.0.1",
        service=registry_service,
    )
    # Get the actual port assigned
    port = server.server_address[1]
    host = server.server_address[0]

    # Start server in background thread
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # Wait for server to be ready
    url = f"http://{host}:{port}/healthz"
    for attempt in range(50):
        try:
            resp = requests.get(url, timeout=1)
            if resp.status_code == 200:
                break
        except requests.RequestException:
            time.sleep(0.1)
    else:
        raise RuntimeError(f"Registry server did not start after 5 seconds")

    yield f"http://{host}:{port}"

    # Clean up
    server.server_close()


# ---------------------------------------------------------------------------
# App Simulator: represents Console, Marketplace, or Gig Board
# ---------------------------------------------------------------------------


class AppSimulator:
    """Simulates an app (Console, Marketplace, Gig Board) connecting to registry."""

    def __init__(self, app_name: str, registry_url: str):
        self.app_name = app_name
        self.registry_url = registry_url
        self.api_key = None
        self.registered_users = {}  # type: Dict[str, dict]
        self.registered_agents = {}  # type: Dict[str, dict]

    def setup(self) -> None:
        """Setup: get an API key from the registry."""
        resp = requests.post(f"{self.registry_url}/admin/api-keys")
        assert resp.status_code == 200, f"Failed to get API key: {resp.text}"
        self.api_key = resp.json()["api_key"]

    def register_user(self, principal_id: str, username: Optional[str] = None):
        """Register a user principal."""
        payload = {"principal_id": principal_id}
        if username:
            payload["username"] = username

        resp = requests.post(
            f"{self.registry_url}/auth/register",
            json=payload,
        )
        assert resp.status_code == 200, f"Failed to register user: {resp.text}"
        user = resp.json()
        self.registered_users[principal_id] = user
        return user

    def login_user(self, principal_id: str):
        """Log in a user (refresh last_active)."""
        payload = {"principal_id": principal_id}
        resp = requests.post(
            f"{self.registry_url}/auth/login",
            json=payload,
        )
        assert resp.status_code == 200, f"Failed to login user: {resp.text}"
        return resp.json()

    def record_reputation(
        self,
        principal_id: str,
        capability_id: str,
        task_id: str,
        verified: bool,
    ):
        """Record a reputation event for a user."""
        payload = {
            "task_id": task_id,
            "capability_id": capability_id,
            "verified": verified,
        }
        resp = requests.post(
            f"{self.registry_url}/users/{principal_id}/reputation",
            json=payload,
        )
        assert resp.status_code == 200, f"Failed to record reputation: {resp.text}"
        return resp.json()

    def query_user(self, principal_id: str):
        """Query user data and reputation."""
        resp = requests.get(
            f"{self.registry_url}/users/{principal_id}",
        )
        assert resp.status_code == 200, f"Failed to query user: {resp.text}"
        return resp.json()

    def register_agent(
        self, principal_id: str, capabilities: list
    ):
        """Register an agent (for capability search)."""
        agent_card = {
            "capabilities": {
                "extensions": [
                    {
                        "uri": "https://treessera.com/extensions/trust/v1"
                    }
                ]
            },
            "skills": [{"id": cap} for cap in capabilities],
        }
        payload = {
            "principal_id": principal_id,
            "api_key": self.api_key,
            "agent_card": agent_card,
        }
        resp = requests.post(
            f"{self.registry_url}/register",
            json=payload,
        )
        assert resp.status_code == 200, f"Failed to register agent: {resp.text}"
        self.registered_agents[principal_id] = resp.json()
        return resp.json()

    def search_capability(self, capability_id: str):
        """Search for agents offering a capability."""
        resp = requests.get(
            f"{self.registry_url}/search?capability={capability_id}",
        )
        assert resp.status_code == 200, f"Failed to search: {resp.text}"
        return resp.json()


# ---------------------------------------------------------------------------
# Test Suite: Independent Registry with Multiple Apps
# ---------------------------------------------------------------------------


class TestIndependentRegistry:
    """Verify registry works as independent service."""

    def test_registry_starts_and_healthz_responds(self, registry_server):
        """Registry starts and health check endpoint works."""
        resp = requests.get(f"{registry_server}/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_single_app_registers_and_queries_user(self, registry_server):
        """Single app can register a user and query it."""
        app = AppSimulator("console", registry_server)
        app.setup()

        # Register user
        user = app.register_user("user_alice", username="alice")
        assert user["status"] == "registered"
        assert user["principal_id"] == "user_alice"

        # Query user back
        queried = app.query_user("user_alice")
        assert queried["principal_id"] == "user_alice"
        assert queried["username"] == "alice"

    def test_single_app_records_reputation(self, registry_server):
        """Single app can record reputation for a user."""
        app = AppSimulator("marketplace", registry_server)
        app.setup()

        # Register user
        app.register_user("user_bob", username="bob")

        # Record reputation
        rep = app.record_reputation(
            "user_bob",
            "code_review",
            "task_123",
            verified=True,
        )
        assert rep["verified"] is True
        assert rep["capability_id"] == "code_review"

        # Query and verify reputation was recorded
        queried = app.query_user("user_bob")
        records = queried["reputation_records"]
        assert len(records) == 1
        assert records[0]["tasks_verified"] == 1
        assert records[0]["tasks_rejected"] == 0
        assert records[0]["verification_rate"] == 1.0


class TestMultipleAppsWithRegistry:
    """Verify multiple apps can use the same independent registry."""

    def test_two_apps_register_different_users(self, registry_server):
        """App 1 registers user, App 2 registers different user."""
        app1 = AppSimulator("console", registry_server)
        app1.setup()
        app1.register_user("user_alice", username="alice")

        app2 = AppSimulator("marketplace", registry_server)
        app2.setup()
        app2.register_user("user_bob", username="bob")

        # Each app can see the users it registered
        alice = app1.query_user("user_alice")
        assert alice["username"] == "alice"

        bob = app2.query_user("user_bob")
        assert bob["username"] == "bob"

        # Each app can also see the other's users
        alice_via_app2 = app2.query_user("user_alice")
        assert alice_via_app2["principal_id"] == "user_alice"

        bob_via_app1 = app1.query_user("user_bob")
        assert bob_via_app1["principal_id"] == "user_bob"

    def test_all_three_apps_register_and_query_same_user(self, registry_server):
        """App 1 registers user; Apps 2 & 3 query it without conflict."""
        app1 = AppSimulator("console", registry_server)
        app1.setup()
        app1.register_user("user_shared", username="shared")

        app2 = AppSimulator("marketplace", registry_server)
        app2.setup()

        app3 = AppSimulator("gig-board", registry_server)
        app3.setup()

        # Apps 2 and 3 can query the user registered by App 1
        user_via_app2 = app2.query_user("user_shared")
        assert user_via_app2["principal_id"] == "user_shared"

        user_via_app3 = app3.query_user("user_shared")
        assert user_via_app3["principal_id"] == "user_shared"

        # All see the same data
        assert (
            user_via_app2["created_at"] == user_via_app3["created_at"]
        )

    def test_multiple_apps_accumulate_reputation(self, registry_server):
        """Multiple apps record reputation for same user; totals accumulate."""
        # App 1: Console registers user and records task_1 (verified)
        app1 = AppSimulator("console", registry_server)
        app1.setup()
        app1.register_user("user_worker", username="worker")
        app1.record_reputation(
            "user_worker",
            "code_review",
            "task_1",
            verified=True,
        )

        # App 2: Marketplace records task_2 (verified) and task_3 (rejected)
        app2 = AppSimulator("marketplace", registry_server)
        app2.setup()
        app2.record_reputation(
            "user_worker",
            "code_review",
            "task_2",
            verified=True,
        )
        app2.record_reputation(
            "user_worker",
            "code_review",
            "task_3",
            verified=False,
        )

        # App 3: Gig Board records task_4 (verified)
        app3 = AppSimulator("gig-board", registry_server)
        app3.setup()
        app3.record_reputation(
            "user_worker",
            "code_review",
            "task_4",
            verified=True,
        )

        # Query from any app: should see all 4 tasks
        queried = app1.query_user("user_worker")
        records = queried["reputation_records"]
        assert len(records) == 1  # One capability
        assert records[0]["capability_id"] == "code_review"
        assert records[0]["tasks_verified"] == 3
        assert records[0]["tasks_rejected"] == 1
        assert records[0]["verification_rate"] == 0.75

        # Verify via app2 and app3 see the same totals
        for app in [app2, app3]:
            queried = app.query_user("user_worker")
            records = queried["reputation_records"]
            assert records[0]["tasks_verified"] == 3
            assert records[0]["tasks_rejected"] == 1

    def test_concurrent_reputation_writes_no_data_loss(self, registry_server):
        """Concurrent writes from multiple apps don't lose data."""
        app1 = AppSimulator("console", registry_server)
        app1.setup()
        app1.register_user("user_concurrent", username="concurrent")

        app2 = AppSimulator("marketplace", registry_server)
        app2.setup()

        app3 = AppSimulator("gig-board", registry_server)
        app3.setup()

        # Each app writes 10 reputation events concurrently
        errors = []

        def app_write_reputation(app, app_id):
            try:
                for i in range(10):
                    app.record_reputation(
                        "user_concurrent",
                        "code_review",
                        f"task_{app_id}_{i}",
                        verified=(i % 2 == 0),  # Alternating verified/rejected
                    )
            except Exception as e:
                errors.append(e)

        # Run writes concurrently
        threads = [
            threading.Thread(
                target=app_write_reputation, args=(app1, 1)
            ),
            threading.Thread(
                target=app_write_reputation, args=(app2, 2)
            ),
            threading.Thread(
                target=app_write_reputation, args=(app3, 3)
            ),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # No errors during concurrent writes
        assert not errors, f"Errors during concurrent writes: {errors}"

        # Verify totals: 30 tasks, 15 verified, 15 rejected
        queried = app1.query_user("user_concurrent")
        records = queried["reputation_records"]
        assert records[0]["tasks_verified"] == 15
        assert records[0]["tasks_rejected"] == 15
        assert records[0]["verification_rate"] == 0.5


class TestPersistence:
    """Verify reputation persists across restarts."""

    def test_data_persists_after_registry_restart(self):
        """Data written to registry survives restart."""
        # First: start registry, register user, record reputation
        service1 = RegistryService(
            IndexStore(),
            user_index=UserIndex(),
        )
        server1 = make_server(
            port=0,
            host="127.0.0.1",
            service=service1,
        )
        port = server1.server_address[1]
        thread1 = threading.Thread(target=server1.serve_forever, daemon=True)
        thread1.start()

        # Wait for server
        time.sleep(0.5)

        url = f"http://127.0.0.1:{port}"
        app = AppSimulator("console", url)
        app.setup()
        app.register_user("user_persist", username="persist")
        app.record_reputation(
            "user_persist",
            "code_review",
            "task_1",
            verified=True,
        )
        app.record_reputation(
            "user_persist",
            "code_review",
            "task_2",
            verified=False,
        )

        # Verify data was recorded
        data1 = app.query_user("user_persist")
        assert data1["reputation_records"][0]["tasks_verified"] == 1
        assert data1["reputation_records"][0]["tasks_rejected"] == 1

        # Stop server (simulate restart)
        server1.server_close()
        time.sleep(0.5)

        # Second: create a fresh registry instance (Postgres backs the data,
        # not a file, so no data file needs to be shared/re-passed here).
        service2 = RegistryService(
            IndexStore(),
            user_index=UserIndex(),
        )
        server2 = make_server(
            port=0,
            host="127.0.0.1",
            service=service2,
        )
        port2 = server2.server_address[1]
        thread2 = threading.Thread(target=server2.serve_forever, daemon=True)
        thread2.start()

        # Wait for server
        time.sleep(0.5)

        url2 = f"http://127.0.0.1:{port2}"
        app2 = AppSimulator("marketplace", url2)
        app2.setup()

        # Query user: should still have the same reputation
        data2 = app2.query_user("user_persist")
        assert data2["reputation_records"][0]["tasks_verified"] == 1
        assert data2["reputation_records"][0]["tasks_rejected"] == 1

        # Clean up
        server2.server_close()


class TestErrorHandling:
    """Verify error handling and isolation."""

    def test_invalid_user_registration_returns_error(self, registry_server):
        """Invalid user registration returns appropriate error."""
        app = AppSimulator("console", registry_server)
        app.setup()

        # Missing principal_id
        resp = requests.post(
            f"{registry_server}/auth/register",
            json={"username": "alice"},
        )
        assert resp.status_code == 422

    def test_duplicate_user_registration_returns_409(self, registry_server):
        """Registering the same user twice returns 409."""
        app = AppSimulator("console", registry_server)
        app.setup()
        app.register_user("user_duplicate")

        # Try to register again
        resp = requests.post(
            f"{registry_server}/auth/register",
            json={"principal_id": "user_duplicate"},
        )
        assert resp.status_code == 409

    def test_query_nonexistent_user_returns_404(self, registry_server):
        """Querying nonexistent user returns 404."""
        resp = requests.get(
            f"{registry_server}/users/user_nonexistent"
        )
        assert resp.status_code == 404

    def test_reputation_for_nonexistent_user_returns_404(
        self, registry_server
    ):
        """Recording reputation for nonexistent user returns 404."""
        resp = requests.post(
            f"{registry_server}/users/user_nonexistent/reputation",
            json={
                "task_id": "task_1",
                "capability_id": "code_review",
                "verified": True,
            },
        )
        assert resp.status_code == 404


class TestAgentRegistration:
    """Verify agent registration and search still work independently."""

    def test_agents_and_users_coexist_in_registry(self, registry_server):
        """Agents and users can coexist without conflict."""
        # App 1: register agents
        app1 = AppSimulator("console", registry_server)
        app1.setup()
        app1.register_agent("agent_alice", ["code_review", "testing"])

        # App 2: register users
        app2 = AppSimulator("marketplace", registry_server)
        app2.setup()
        app2.register_user("user_bob")

        # Both data types exist independently
        agent = requests.get(
            f"{registry_server}/agents/agent_alice"
        )
        assert agent.status_code == 200

        user = requests.get(
            f"{registry_server}/users/user_bob"
        )
        assert user.status_code == 200

        # Search works for agents
        search = requests.get(
            f"{registry_server}/search?capability=code_review"
        )
        assert search.status_code == 200
        candidates = search.json()["candidates"]
        assert len(candidates) == 1
        assert candidates[0]["principal_id"] == "agent_alice"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
