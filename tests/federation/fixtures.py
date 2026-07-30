"""Shared fixtures for federation end-to-end tests.

Provides:
- Registry setup (in-process or via HTTP)
- App server startup (Console, Marketplace, Gig Board)
- AppClient wrapper for testing HTTP interactions
- Cleanup utilities
"""

import threading
import time
from typing import Dict, Optional, Tuple

import pytest
import requests

from apps.marketplace.server.app import make_server as make_marketplace_server
from apps.gig_board.server.app import make_server as make_gig_board_server
from registry.app import RegistryService, make_server as make_registry_server
from registry.index_store import IndexStore
from registry.user_index import UserIndex


def free_port():
    """Find a free port for server binding."""
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def start_server_background(server):
    """Start an HTTP server in a background daemon thread."""
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def wait_for_server(url, max_attempts=50, delay=0.1):
    """Wait for a server to become available via HTTP."""
    for attempt in range(max_attempts):
        try:
            resp = requests.get(url + "/healthz", timeout=1)
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(delay)
    return False


class AppClient:
    """HTTP client for interacting with an app (Console, Marketplace, Gig Board)."""

    def __init__(self, app_name: str, base_url: str, registry_url: Optional[str] = None):
        self.app_name = app_name
        self.base_url = base_url.rstrip("/")
        self.registry_url = (registry_url.rstrip("/") if registry_url else base_url.rstrip("/"))
        self.timeout = 5.0

    def healthz(self) -> bool:
        """Check if app is healthy."""
        try:
            resp = requests.get(f"{self.base_url}/healthz", timeout=self.timeout)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    # ========== User Authentication (Registry) ==========

    def register_user(self, principal_id: str, username: Optional[str] = None) -> dict:
        """Register a user in the registry."""
        payload = {"principal_id": principal_id}
        if username:
            payload["username"] = username

        resp = requests.post(
            f"{self.registry_url}/auth/register",
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to register user: {resp.text}")
        return resp.json()

    def login_user(self, principal_id: str) -> dict:
        """Log in a user (via registry)."""
        payload = {"principal_id": principal_id}
        resp = requests.post(
            f"{self.registry_url}/auth/login",
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to login user: {resp.text}")
        return resp.json()

    def get_user(self, principal_id: str) -> dict:
        """Get user data and reputation."""
        resp = requests.get(
            f"{self.registry_url}/users/{principal_id}",
            timeout=self.timeout,
        )
        if resp.status_code == 404:
            raise RuntimeError(f"User not found: {principal_id}")
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to get user: {resp.text}")
        return resp.json()

    def record_reputation(
        self,
        principal_id: str,
        task_id: str,
        capability_id: str,
        verified: bool = True,
    ) -> dict:
        """Record reputation for a user."""
        payload = {
            "task_id": task_id,
            "capability_id": capability_id,
            "verified": verified,
        }
        resp = requests.post(
            f"{self.registry_url}/users/{principal_id}/reputation",
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to record reputation: {resp.text}")
        return resp.json()

    # ========== Marketplace API ==========

    def create_task(self, principal_id: str, description: str) -> dict:
        """Create a task (Marketplace only)."""
        payload = {
            "principal_id": principal_id,
            "description": description,
        }
        resp = requests.post(
            f"{self.base_url}/api/tasks",
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to create task: {resp.text}")
        return resp.json()["task"]

    def list_tasks(self, skip: int = 0, limit: int = 50) -> Tuple[list, int]:
        """List all tasks (Marketplace only)."""
        resp = requests.get(
            f"{self.base_url}/api/tasks?skip={skip}&limit={limit}",
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to list tasks: {resp.text}")
        data = resp.json()
        return data["tasks"], data["total"]

    def get_task(self, task_id: str) -> dict:
        """Get task details (Marketplace only)."""
        resp = requests.get(
            f"{self.base_url}/api/tasks/{task_id}",
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to get task: {resp.text}")
        return resp.json()["task"]

    def accept_task(self, task_id: str, worker_principal: str) -> dict:
        """Accept a task (Marketplace only)."""
        payload = {
            "worker_principal": worker_principal,
        }
        resp = requests.post(
            f"{self.base_url}/api/tasks/{task_id}/accept",
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to accept task: {resp.text}")
        return resp.json()["task"]

    def send_negotiation_message(
        self, task_id: str, from_principal: str, message: str
    ) -> dict:
        """Send negotiation message (Marketplace only)."""
        payload = {
            "from_principal": from_principal,
            "message": message,
        }
        resp = requests.post(
            f"{self.base_url}/api/negotiations/{task_id}",
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to send negotiation message: {resp.text}")
        return resp.json()["message"]

    def get_negotiations(self, task_id: str) -> list:
        """Get negotiation thread (Marketplace only)."""
        resp = requests.get(
            f"{self.base_url}/api/negotiations/{task_id}",
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to get negotiations: {resp.text}")
        return resp.json()["negotiations"]

    def complete_task(
        self, task_id: str, author_principal: str, outcome: str
    ) -> dict:
        """Complete a task (Marketplace only)."""
        payload = {
            "author_principal": author_principal,
            "outcome": outcome,
        }
        resp = requests.post(
            f"{self.base_url}/api/negotiations/{task_id}/complete",
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to complete task: {resp.text}")
        return resp.json()["task"]

    # ========== Gig Board API (Service Provider Model) ==========

    def register_service(self, principal_id: str, service_name: str, description: str) -> dict:
        """Register as a service provider (Gig Board only)."""
        payload = {
            "principal_id": principal_id,
            "service_name": service_name,
            "description": description,
        }
        resp = requests.post(
            f"{self.base_url}/api/services",
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to register service: {resp.text}")
        return resp.json()["service"]

    def list_services(self, skip: int = 0, limit: int = 50) -> Tuple[list, int]:
        """List all service providers (Gig Board only)."""
        resp = requests.get(
            f"{self.base_url}/api/services?skip={skip}&limit={limit}",
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to list services: {resp.text}")
        data = resp.json()
        return data["services"], data["total"]

    def get_service(self, service_id: str) -> dict:
        """Get service details (Gig Board only)."""
        resp = requests.get(
            f"{self.base_url}/api/services/{service_id}",
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to get service: {resp.text}")
        return resp.json()["service"]

    def create_gig(self, service_id: str, buyer_principal: str, description: str) -> dict:
        """Create a gig (hire a service provider) (Gig Board only)."""
        payload = {
            "service_id": service_id,
            "buyer_principal": buyer_principal,
            "description": description,
        }
        resp = requests.post(
            f"{self.base_url}/api/gigs",
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to create gig: {resp.text}")
        return resp.json()["gig"]

    def list_gigs(self, principal_id: str, skip: int = 0, limit: int = 50) -> Tuple[list, int]:
        """List gigs for a user (Gig Board only)."""
        resp = requests.get(
            f"{self.base_url}/api/gigs?principal_id={principal_id}&skip={skip}&limit={limit}",
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to list gigs: {resp.text}")
        data = resp.json()
        return data["gigs"], data["total"]

    def complete_gig(
        self, gig_id: str, buyer_principal: str, outcome: str
    ) -> dict:
        """Complete a gig and record reputation (Gig Board only)."""
        payload = {
            "buyer_principal": buyer_principal,
            "outcome": outcome,
        }
        resp = requests.post(
            f"{self.base_url}/api/gigs/{gig_id}/complete",
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to complete gig: {resp.text}")
        return resp.json()["gig"]


# ========== Pytest Fixtures ==========


@pytest.fixture
def registry_service():
    """Create a RegistryService (Postgres-backed, unit U5)."""
    index = IndexStore()
    user_index = UserIndex()
    return RegistryService(index, user_index=user_index)


@pytest.fixture
def registry_server(registry_service):
    """Start a registry server and clean up after test."""
    port = free_port()
    server = make_registry_server(port=port, host="127.0.0.1", service=registry_service)
    thread = start_server_background(server)

    # Wait for server to be ready
    url = f"http://127.0.0.1:{port}"
    if not wait_for_server(url):
        raise RuntimeError("Registry server failed to start")

    yield url

    # Cleanup
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


@pytest.fixture
def marketplace_server(registry_server):
    """Start a Marketplace server connected to registry."""
    port = free_port()
    server = make_marketplace_server(
        port=port,
        host="127.0.0.1",
        registry_url=registry_server,
    )
    thread = start_server_background(server)

    # Wait for server to be ready
    url = f"http://127.0.0.1:{port}"
    if not wait_for_server(url):
        raise RuntimeError("Marketplace server failed to start")

    yield url

    # Cleanup
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


@pytest.fixture
def gig_board_server(registry_server):
    """Start a Gig Board server connected to registry."""
    port = free_port()
    server = make_gig_board_server(
        port=port,
        host="127.0.0.1",
        registry_url=registry_server,
    )
    thread = start_server_background(server)

    # Wait for server to be ready
    url = f"http://127.0.0.1:{port}"
    if not wait_for_server(url):
        raise RuntimeError("Gig Board server failed to start")

    yield url

    # Cleanup
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


@pytest.fixture
def registry_client(registry_server):
    """Registry HTTP client."""
    return AppClient("registry", registry_server, registry_url=registry_server)


@pytest.fixture
def marketplace_client(marketplace_server, registry_server):
    """Marketplace HTTP client."""
    return AppClient("marketplace", marketplace_server, registry_url=registry_server)


@pytest.fixture
def gig_board_client(gig_board_server, registry_server):
    """Gig Board HTTP client."""
    return AppClient("gig-board", gig_board_server, registry_url=registry_server)


@pytest.fixture
def all_apps(registry_server, marketplace_server, gig_board_server):
    """Fixture providing all 3 app servers."""
    return {
        "registry": registry_server,
        "marketplace": marketplace_server,
        "gig_board": gig_board_server,
    }


@pytest.fixture
def all_clients(registry_client, marketplace_client, gig_board_client):
    """Fixture providing all 3 app clients."""
    return {
        "registry": registry_client,
        "marketplace": marketplace_client,
        "gig_board": gig_board_client,
    }
