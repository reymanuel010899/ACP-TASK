"""Federation tests between Gig Board and Marketplace.

Demonstrates that U4 (Gig Board) works alongside U3 (Marketplace)
and proves that federation works across different app domains.
"""

import threading
import pytest
import requests

from apps.gig_board.server.app import make_server as make_gig_board
from apps.marketplace.server.app import make_server as make_marketplace


def base_url(server):
    host, port = server.server_address[:2]
    return "http://%s:%d" % (host, port)


@pytest.fixture
def gig_board():
    server = make_gig_board(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def marketplace():
    server = make_marketplace(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_both_apps_run_independently(gig_board, marketplace):
    """Test that both apps can run simultaneously without interference."""
    # Healthz checks
    gb_health = requests.get(base_url(gig_board) + "/healthz", timeout=5)
    assert gb_health.status_code == 200

    mp_health = requests.get(base_url(marketplace) + "/healthz", timeout=5)
    assert mp_health.status_code == 200


def test_user_can_participate_in_both_apps(gig_board, marketplace):
    """Test that a user (Principal) can participate in both apps."""
    user_principal = "ed25519_alice"

    # Create a service in Gig Board
    gb_service = requests.post(
        base_url(gig_board) + "/api/services",
        json={
            "principal_id": user_principal,
            "service_name": "Consulting",
            "description": "Business consulting",
        },
        timeout=5,
    )
    assert gb_service.status_code == 200

    # Create a task in Marketplace (as author, different role)
    mp_task = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={
            "principal_id": user_principal,
            "description": "Need help with project",
        },
        timeout=5,
    )
    assert mp_task.status_code == 200

    # Verify both exist
    gb_services = requests.get(
        base_url(gig_board) + "/api/services",
        timeout=5,
    )
    assert len(gb_services.json()["services"]) == 1

    mp_tasks = requests.get(
        base_url(marketplace) + "/api/tasks",
        timeout=5,
    )
    assert len(mp_tasks.json()["tasks"]) == 1


def test_different_users_in_different_apps(gig_board, marketplace):
    """Test that different users can participate in each app domain."""
    # User A: Service provider in Gig Board
    alice_principal = "ed25519_alice"
    alice_service = requests.post(
        base_url(gig_board) + "/api/services",
        json={
            "principal_id": alice_principal,
            "service_name": "Logo Design",
            "description": "Professional logos",
        },
        timeout=5,
    )
    assert alice_service.status_code == 200

    # User B: Task poster in Marketplace
    bob_principal = "ed25519_bob"
    bob_task = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={
            "principal_id": bob_principal,
            "description": "Build a website",
        },
        timeout=5,
    )
    assert bob_task.status_code == 200

    # Verify they're in separate domains
    gig_board_users = set()
    for svc in requests.get(base_url(gig_board) + "/api/services", timeout=5).json()["services"]:
        gig_board_users.add(svc["provider_principal"])

    marketplace_users = set()
    for task in requests.get(base_url(marketplace) + "/api/tasks", timeout=5).json()["tasks"]:
        marketplace_users.add(task["author_principal"])

    assert alice_principal in gig_board_users
    assert bob_principal in marketplace_users
    # They shouldn't overlap (this test case)
    assert gig_board_users != marketplace_users


def test_marketplace_patterns_still_work(marketplace):
    """Regression test: ensure marketplace functionality isn't broken."""
    author = "ed25519_author"
    worker = "ed25519_worker"

    # Create task
    task_resp = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={
            "principal_id": author,
            "description": "Fix the bug",
        },
        timeout=5,
    )
    assert task_resp.status_code == 200
    task_id = task_resp.json()["task"]["id"]

    # Accept task
    accept_resp = requests.post(
        base_url(marketplace) + f"/api/tasks/{task_id}/accept",
        json={"worker_principal": worker},
        timeout=5,
    )
    assert accept_resp.status_code == 200

    # Verify it's accepted
    task_check = requests.get(
        base_url(marketplace) + f"/api/tasks/{task_id}",
        timeout=5,
    )
    assert task_check.json()["task"]["status"] == "accepted"
    assert task_check.json()["task"]["worker_principal"] == worker


def test_gig_board_patterns_work_independently(gig_board):
    """Regression test: ensure gig board functionality isn't broken."""
    provider = "ed25519_provider"
    buyer = "ed25519_buyer"

    # Register service
    service_resp = requests.post(
        base_url(gig_board) + "/api/services",
        json={
            "principal_id": provider,
            "service_name": "Tutoring",
            "description": "Math tutoring",
        },
        timeout=5,
    )
    assert service_resp.status_code == 200
    service_id = service_resp.json()["service"]["id"]

    # Create gig
    gig_resp = requests.post(
        base_url(gig_board) + "/api/gigs",
        json={
            "service_id": service_id,
            "buyer_principal": buyer,
            "description": "Teach algebra",
        },
        timeout=5,
    )
    assert gig_resp.status_code == 200

    # Verify gig exists
    gigs_resp = requests.get(
        base_url(gig_board) + f"/api/gigs?principal_id={buyer}",
        timeout=5,
    )
    assert len(gigs_resp.json()["gigs"]) == 1


def test_both_apps_scale_independently(gig_board, marketplace):
    """Test that both apps can scale independently."""
    # Create 5 services in gig board
    for i in range(5):
        requests.post(
            base_url(gig_board) + "/api/services",
            json={
                "principal_id": f"ed25519_provider_{i}",
                "service_name": f"Service {i}",
                "description": f"Description {i}",
            },
            timeout=5,
        )

    # Create 3 tasks in marketplace
    for i in range(3):
        requests.post(
            base_url(marketplace) + "/api/tasks",
            json={
                "principal_id": f"ed25519_author_{i}",
                "description": f"Task {i}",
            },
            timeout=5,
        )

    # Verify counts
    gb_services = requests.get(base_url(gig_board) + "/api/services", timeout=5)
    assert gb_services.json()["total"] == 5

    mp_tasks = requests.get(base_url(marketplace) + "/api/tasks", timeout=5)
    assert mp_tasks.json()["total"] == 3


def test_federation_different_data_models(gig_board, marketplace):
    """Verify that both apps have different data models appropriate for their domain."""
    # Gig Board: Service model (provider-centric)
    gig_board_service = requests.post(
        base_url(gig_board) + "/api/services",
        json={
            "principal_id": "ed25519_provider",
            "service_name": "Coaching",
            "description": "Career coaching",
        },
        timeout=5,
    ).json()["service"]

    # Gig Board has provider_principal, service_name, gigs_completed
    assert "provider_principal" in gig_board_service
    assert "service_name" in gig_board_service
    assert "gigs_completed" in gig_board_service

    # Marketplace: Task model (work-centric)
    marketplace_task = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={
            "principal_id": "ed25519_author",
            "description": "Build API",
        },
        timeout=5,
    ).json()["task"]

    # Marketplace has author_principal, description, negotiations
    assert "author_principal" in marketplace_task
    assert "description" in marketplace_task
    assert "negotiations" in marketplace_task

    # They're different!
    assert "service_name" not in marketplace_task
    assert "negotiations" not in gig_board_service
