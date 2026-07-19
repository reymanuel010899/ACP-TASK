"""Tests for the Gig Board (unit U4).

Boots the gig board server and drives it over HTTP exactly as the frontend would,
verifying the full gig lifecycle: register service -> browse -> hire -> complete -> reputation recorded.
"""

import json
import socket
import threading

import pytest
import requests

from apps.gig_board.server.app import make_server


def base_url(server):
    host, port = server.server_address[:2]
    return "http://%s:%d" % (host, port)


@pytest.fixture
def gig_board():
    server = make_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_healthz(gig_board):
    """Test the /healthz endpoint."""
    resp = requests.get(base_url(gig_board) + "/healthz", timeout=5)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_register_service(gig_board):
    """Test registering as a service provider."""
    resp = requests.post(
        base_url(gig_board) + "/api/services",
        json={
            "principal_id": "ed25519_provider_1",
            "service_name": "Web Development",
            "description": "Full-stack web development services",
        },
        timeout=5,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "service" in data
    service = data["service"]
    assert service["id"]
    assert service["provider_principal"] == "ed25519_provider_1"
    assert service["service_name"] == "Web Development"
    assert service["description"] == "Full-stack web development services"
    assert service["gigs_completed"] == 0
    assert service["rating"] is None
    assert "created_at" in service


def test_register_service_missing_fields(gig_board):
    """Test registering service with missing fields."""
    resp = requests.post(
        base_url(gig_board) + "/api/services",
        json={"service_name": "Web Dev"},
        timeout=5,
    )
    assert resp.status_code == 422
    assert "principal_id" in resp.json()["error"]

    resp = requests.post(
        base_url(gig_board) + "/api/services",
        json={"principal_id": "ed25519_user_1"},
        timeout=5,
    )
    assert resp.status_code == 422
    assert "service_name" in resp.json()["error"]


def test_list_services_empty(gig_board):
    """Test listing services when none exist."""
    resp = requests.get(base_url(gig_board) + "/api/services", timeout=5)
    assert resp.status_code == 200
    data = resp.json()
    assert data["services"] == []
    assert data["total"] == 0
    assert data["skip"] == 0
    assert data["limit"] == 50


def test_list_services_pagination(gig_board):
    """Test listing services with pagination."""
    # Create 3 services
    for i in range(3):
        requests.post(
            base_url(gig_board) + "/api/services",
            json={
                "principal_id": f"ed25519_provider_{i}",
                "service_name": f"Service {i}",
                "description": f"Description {i}",
            },
            timeout=5,
        )

    # List with limit
    resp = requests.get(
        base_url(gig_board) + "/api/services?skip=0&limit=2",
        timeout=5,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["services"]) == 2
    assert data["total"] == 3
    assert data["limit"] == 2


def test_get_service(gig_board):
    """Test getting a specific service."""
    create_resp = requests.post(
        base_url(gig_board) + "/api/services",
        json={
            "principal_id": "ed25519_provider_1",
            "service_name": "Design",
            "description": "Graphic design",
        },
        timeout=5,
    )
    service_id = create_resp.json()["service"]["id"]

    resp = requests.get(
        base_url(gig_board) + f"/api/services/{service_id}",
        timeout=5,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["service"]["id"] == service_id
    assert data["service"]["service_name"] == "Design"


def test_get_nonexistent_service(gig_board):
    """Test getting a service that doesn't exist."""
    resp = requests.get(
        base_url(gig_board) + "/api/services/nonexistent",
        timeout=5,
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["error"]


def test_create_gig(gig_board):
    """Test creating a gig (hiring a provider)."""
    # Register a service first
    service_resp = requests.post(
        base_url(gig_board) + "/api/services",
        json={
            "principal_id": "ed25519_provider_1",
            "service_name": "Logo Design",
            "description": "Professional logo design",
        },
        timeout=5,
    )
    service_id = service_resp.json()["service"]["id"]

    # Create a gig
    gig_resp = requests.post(
        base_url(gig_board) + "/api/gigs",
        json={
            "service_id": service_id,
            "buyer_principal": "ed25519_buyer_1",
            "description": "Need a logo for my startup",
        },
        timeout=5,
    )
    assert gig_resp.status_code == 200
    gig = gig_resp.json()["gig"]
    assert gig["id"]
    assert gig["service_id"] == service_id
    assert gig["provider_principal"] == "ed25519_provider_1"
    assert gig["buyer_principal"] == "ed25519_buyer_1"
    assert gig["description"] == "Need a logo for my startup"
    assert gig["status"] == "active"
    assert gig["outcome"] is None


def test_create_gig_missing_fields(gig_board):
    """Test creating a gig with missing fields."""
    resp = requests.post(
        base_url(gig_board) + "/api/gigs",
        json={"buyer_principal": "ed25519_buyer_1"},
        timeout=5,
    )
    assert resp.status_code == 422
    assert "service_id" in resp.json()["error"]


def test_create_gig_nonexistent_service(gig_board):
    """Test creating a gig for a nonexistent service."""
    resp = requests.post(
        base_url(gig_board) + "/api/gigs",
        json={
            "service_id": "nonexistent",
            "buyer_principal": "ed25519_buyer_1",
            "description": "Test",
        },
        timeout=5,
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["error"]


def test_cannot_hire_yourself(gig_board):
    """Test that you cannot hire yourself."""
    service_resp = requests.post(
        base_url(gig_board) + "/api/services",
        json={
            "principal_id": "ed25519_provider_1",
            "service_name": "Consulting",
            "description": "Business consulting",
        },
        timeout=5,
    )
    service_id = service_resp.json()["service"]["id"]

    # Try to hire yourself
    gig_resp = requests.post(
        base_url(gig_board) + "/api/gigs",
        json={
            "service_id": service_id,
            "buyer_principal": "ed25519_provider_1",
            "description": "Help me",
        },
        timeout=5,
    )
    assert gig_resp.status_code == 400
    assert "cannot hire yourself" in gig_resp.json()["error"]


def test_list_gigs_by_principal(gig_board):
    """Test listing gigs for a specific principal."""
    # Create a service and a gig
    service_resp = requests.post(
        base_url(gig_board) + "/api/services",
        json={
            "principal_id": "ed25519_provider_1",
            "service_name": "Coaching",
            "description": "Life coaching",
        },
        timeout=5,
    )
    service_id = service_resp.json()["service"]["id"]

    gig_resp = requests.post(
        base_url(gig_board) + "/api/gigs",
        json={
            "service_id": service_id,
            "buyer_principal": "ed25519_buyer_1",
            "description": "Need guidance",
        },
        timeout=5,
    )

    # List gigs for the buyer
    list_resp = requests.get(
        base_url(gig_board) + "/api/gigs?principal_id=ed25519_buyer_1",
        timeout=5,
    )
    assert list_resp.status_code == 200
    gigs = list_resp.json()["gigs"]
    assert len(gigs) == 1
    assert gigs[0]["buyer_principal"] == "ed25519_buyer_1"

    # List gigs for the provider
    list_resp = requests.get(
        base_url(gig_board) + "/api/gigs?principal_id=ed25519_provider_1",
        timeout=5,
    )
    assert list_resp.status_code == 200
    gigs = list_resp.json()["gigs"]
    assert len(gigs) == 1
    assert gigs[0]["provider_principal"] == "ed25519_provider_1"


def test_complete_gig(gig_board):
    """Test completing a gig."""
    # Create service and gig
    service_resp = requests.post(
        base_url(gig_board) + "/api/services",
        json={
            "principal_id": "ed25519_provider_1",
            "service_name": "Writing",
            "description": "Content writing",
        },
        timeout=5,
    )
    service_id = service_resp.json()["service"]["id"]

    gig_resp = requests.post(
        base_url(gig_board) + "/api/gigs",
        json={
            "service_id": service_id,
            "buyer_principal": "ed25519_buyer_1",
            "description": "Write blog posts",
        },
        timeout=5,
    )
    gig_id = gig_resp.json()["gig"]["id"]

    # Complete the gig
    complete_resp = requests.post(
        base_url(gig_board) + f"/api/gigs/{gig_id}/complete",
        json={
            "buyer_principal": "ed25519_buyer_1",
            "outcome": "Great work, delivered on time",
        },
        timeout=5,
    )
    assert complete_resp.status_code == 200
    gig = complete_resp.json()["gig"]
    assert gig["status"] == "completed"
    assert gig["outcome"] == "Great work, delivered on time"
    assert gig["completed_at"] is not None


def test_complete_gig_only_buyer_can_complete(gig_board):
    """Test that only the buyer can complete a gig."""
    # Create service and gig
    service_resp = requests.post(
        base_url(gig_board) + "/api/services",
        json={
            "principal_id": "ed25519_provider_1",
            "service_name": "Tutoring",
            "description": "Math tutoring",
        },
        timeout=5,
    )
    service_id = service_resp.json()["service"]["id"]

    gig_resp = requests.post(
        base_url(gig_board) + "/api/gigs",
        json={
            "service_id": service_id,
            "buyer_principal": "ed25519_buyer_1",
            "description": "Teach algebra",
        },
        timeout=5,
    )
    gig_id = gig_resp.json()["gig"]["id"]

    # Try to complete as provider (should fail)
    complete_resp = requests.post(
        base_url(gig_board) + f"/api/gigs/{gig_id}/complete",
        json={
            "buyer_principal": "ed25519_provider_1",
            "outcome": "Done",
        },
        timeout=5,
    )
    assert complete_resp.status_code == 403
    assert "only gig buyer can complete" in complete_resp.json()["error"]


def test_cannot_complete_nonexistent_gig(gig_board):
    """Test completing a gig that doesn't exist."""
    resp = requests.post(
        base_url(gig_board) + "/api/gigs/nonexistent/complete",
        json={
            "buyer_principal": "ed25519_buyer_1",
            "outcome": "Done",
        },
        timeout=5,
    )
    assert resp.status_code == 404


def test_cannot_complete_already_completed_gig(gig_board):
    """Test that you can't complete a gig twice."""
    # Create and complete a gig
    service_resp = requests.post(
        base_url(gig_board) + "/api/services",
        json={
            "principal_id": "ed25519_provider_1",
            "service_name": "Editing",
            "description": "Proofreading and editing",
        },
        timeout=5,
    )
    service_id = service_resp.json()["service"]["id"]

    gig_resp = requests.post(
        base_url(gig_board) + "/api/gigs",
        json={
            "service_id": service_id,
            "buyer_principal": "ed25519_buyer_1",
            "description": "Edit my paper",
        },
        timeout=5,
    )
    gig_id = gig_resp.json()["gig"]["id"]

    requests.post(
        base_url(gig_board) + f"/api/gigs/{gig_id}/complete",
        json={
            "buyer_principal": "ed25519_buyer_1",
            "outcome": "Done",
        },
        timeout=5,
    )

    # Try to complete again
    complete_resp = requests.post(
        base_url(gig_board) + f"/api/gigs/{gig_id}/complete",
        json={
            "buyer_principal": "ed25519_buyer_1",
            "outcome": "Done again",
        },
        timeout=5,
    )
    assert complete_resp.status_code == 400
    assert "must be active" in complete_resp.json()["error"]


def test_full_gig_lifecycle(gig_board):
    """Test the complete gig lifecycle: register -> list -> hire -> complete."""
    # 1. Provider registers a service
    service_resp = requests.post(
        base_url(gig_board) + "/api/services",
        json={
            "principal_id": "ed25519_alice",
            "service_name": "Algorithm Tutoring",
            "description": "Expert in data structures and algorithms",
        },
        timeout=5,
    )
    assert service_resp.status_code == 200
    service = service_resp.json()["service"]
    assert service["gigs_completed"] == 0

    # 2. Buyer lists services
    list_resp = requests.get(
        base_url(gig_board) + "/api/services",
        timeout=5,
    )
    assert list_resp.status_code == 200
    services = list_resp.json()["services"]
    assert len(services) == 1

    # 3. Buyer hires the provider
    gig_resp = requests.post(
        base_url(gig_board) + "/api/gigs",
        json={
            "service_id": service["id"],
            "buyer_principal": "ed25519_bob",
            "description": "Help me prepare for my coding interview",
        },
        timeout=5,
    )
    assert gig_resp.status_code == 200
    gig = gig_resp.json()["gig"]
    assert gig["status"] == "active"

    # 4. Buyer lists their gigs
    my_gigs_resp = requests.get(
        base_url(gig_board) + "/api/gigs?principal_id=ed25519_bob",
        timeout=5,
    )
    assert my_gigs_resp.status_code == 200
    assert len(my_gigs_resp.json()["gigs"]) == 1

    # 5. Buyer completes the gig
    complete_resp = requests.post(
        base_url(gig_board) + f"/api/gigs/{gig['id']}/complete",
        json={
            "buyer_principal": "ed25519_bob",
            "outcome": "Excellent tutoring, very helpful!",
        },
        timeout=5,
    )
    assert complete_resp.status_code == 200
    completed_gig = complete_resp.json()["gig"]
    assert completed_gig["status"] == "completed"

    # 6. Verify gig is in completed list
    completed_gigs_resp = requests.get(
        base_url(gig_board) + "/api/gigs?principal_id=ed25519_bob",
        timeout=5,
    )
    gigs = completed_gigs_resp.json()["gigs"]
    assert len(gigs) == 1
    assert gigs[0]["status"] == "completed"


def test_gig_updates_service_stats(gig_board):
    """Test that completing gigs updates service completion count."""
    # Register service
    service_resp = requests.post(
        base_url(gig_board) + "/api/services",
        json={
            "principal_id": "ed25519_provider",
            "service_name": "Translation",
            "description": "Professional translation services",
        },
        timeout=5,
    )
    service_id = service_resp.json()["service"]["id"]

    # Create and complete a gig
    gig_resp = requests.post(
        base_url(gig_board) + "/api/gigs",
        json={
            "service_id": service_id,
            "buyer_principal": "ed25519_buyer",
            "description": "Translate document",
        },
        timeout=5,
    )
    gig_id = gig_resp.json()["gig"]["id"]

    requests.post(
        base_url(gig_board) + f"/api/gigs/{gig_id}/complete",
        json={
            "buyer_principal": "ed25519_buyer",
            "outcome": "Perfect",
        },
        timeout=5,
    )

    # Check service stats
    service_check = requests.get(
        base_url(gig_board) + f"/api/services/{service_id}",
        timeout=5,
    )
    updated_service = service_check.json()["service"]
    assert updated_service["gigs_completed"] == 1
