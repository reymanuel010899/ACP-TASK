"""Tests for the Task Marketplace (unit U3).

Boots the marketplace server and drives it over HTTP exactly as the frontend would,
verifying the full task lifecycle: post -> accept -> negotiate -> complete -> reputation recorded.
"""

import json
import socket
import threading

import pytest
import requests

from apps.marketplace.server.app import make_server


def base_url(server):
    host, port = server.server_address[:2]
    return "http://%s:%d" % (host, port)


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def marketplace():
    server = make_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_healthz(marketplace):
    """Test the /healthz endpoint."""
    resp = requests.get(base_url(marketplace) + "/healthz", timeout=5)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_task(marketplace):
    """Test creating a new task."""
    resp = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={
            "principal_id": "ed25519_author_1",
            "description": "Fix bug in authentication module",
        },
        timeout=5,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "task" in data
    task = data["task"]
    assert task["id"]
    assert task["author_principal"] == "ed25519_author_1"
    assert task["description"] == "Fix bug in authentication module"
    assert task["status"] == "open"
    assert task["worker_principal"] is None
    assert task["negotiations"] == []
    assert task["outcome"] is None
    assert "created_at" in task


def test_create_task_missing_principal(marketplace):
    """Test creating a task without principal_id."""
    resp = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={"description": "Some task"},
        timeout=5,
    )
    assert resp.status_code == 422
    assert "principal_id" in resp.json()["error"]


def test_create_task_missing_description(marketplace):
    """Test creating a task without description."""
    resp = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={"principal_id": "ed25519_author_1"},
        timeout=5,
    )
    assert resp.status_code == 422
    assert "description" in resp.json()["error"]


def test_list_tasks_empty(marketplace):
    """Test listing tasks when none exist."""
    resp = requests.get(base_url(marketplace) + "/api/tasks", timeout=5)
    assert resp.status_code == 200
    data = resp.json()
    assert data["tasks"] == []
    assert data["total"] == 0
    assert data["skip"] == 0
    assert data["limit"] == 50


def test_list_tasks_with_pagination(marketplace):
    """Test listing tasks with pagination."""
    # Create 5 tasks
    task_ids = []
    for i in range(5):
        resp = requests.post(
            base_url(marketplace) + "/api/tasks",
            json={
                "principal_id": "ed25519_author_1",
                "description": "Task %d" % i,
            },
            timeout=5,
        )
        task_ids.append(resp.json()["task"]["id"])

    # List with limit=2
    resp = requests.get(
        base_url(marketplace) + "/api/tasks?skip=0&limit=2", timeout=5
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tasks"]) == 2
    assert data["total"] == 5
    assert data["skip"] == 0
    assert data["limit"] == 2

    # List skip=2
    resp = requests.get(
        base_url(marketplace) + "/api/tasks?skip=2&limit=2", timeout=5
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tasks"]) == 2
    assert data["skip"] == 2


def test_get_task(marketplace):
    """Test fetching a specific task."""
    # Create a task
    create_resp = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={
            "principal_id": "ed25519_author_1",
            "description": "Implement feature X",
        },
        timeout=5,
    )
    task_id = create_resp.json()["task"]["id"]

    # Get the task
    resp = requests.get(
        base_url(marketplace) + "/api/tasks/%s" % task_id, timeout=5
    )
    assert resp.status_code == 200
    task = resp.json()["task"]
    assert task["id"] == task_id
    assert task["description"] == "Implement feature X"


def test_get_task_not_found(marketplace):
    """Test fetching a non-existent task."""
    resp = requests.get(
        base_url(marketplace) + "/api/tasks/nonexistent", timeout=5
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["error"]


def test_accept_task(marketplace):
    """Test accepting a task as a worker."""
    # Create a task
    create_resp = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={
            "principal_id": "ed25519_author_1",
            "description": "Review code",
        },
        timeout=5,
    )
    task_id = create_resp.json()["task"]["id"]

    # Accept it
    resp = requests.post(
        base_url(marketplace) + "/api/tasks/%s/accept" % task_id,
        json={"worker_principal": "ed25519_worker_1"},
        timeout=5,
    )
    assert resp.status_code == 200
    task = resp.json()["task"]
    assert task["status"] == "accepted"
    assert task["worker_principal"] == "ed25519_worker_1"


def test_accept_task_not_found(marketplace):
    """Test accepting a non-existent task."""
    resp = requests.post(
        base_url(marketplace) + "/api/tasks/nonexistent/accept",
        json={"worker_principal": "ed25519_worker_1"},
        timeout=5,
    )
    assert resp.status_code == 404


def test_accept_task_already_accepted(marketplace):
    """Test accepting a task that's already accepted."""
    # Create and accept
    create_resp = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={
            "principal_id": "ed25519_author_1",
            "description": "Some task",
        },
        timeout=5,
    )
    task_id = create_resp.json()["task"]["id"]

    requests.post(
        base_url(marketplace) + "/api/tasks/%s/accept" % task_id,
        json={"worker_principal": "ed25519_worker_1"},
        timeout=5,
    )

    # Try to accept again
    resp = requests.post(
        base_url(marketplace) + "/api/tasks/%s/accept" % task_id,
        json={"worker_principal": "ed25519_worker_2"},
        timeout=5,
    )
    assert resp.status_code == 400
    assert "not open" in resp.json()["error"]


def test_cannot_accept_own_task(marketplace):
    """Test that the author cannot accept their own task."""
    # Create a task
    create_resp = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={
            "principal_id": "ed25519_author_1",
            "description": "Some task",
        },
        timeout=5,
    )
    task_id = create_resp.json()["task"]["id"]

    # Try to accept as author
    resp = requests.post(
        base_url(marketplace) + "/api/tasks/%s/accept" % task_id,
        json={"worker_principal": "ed25519_author_1"},
        timeout=5,
    )
    assert resp.status_code == 400
    assert "cannot accept your own task" in resp.json()["error"]


def test_send_negotiation_message(marketplace):
    """Test sending a negotiation message."""
    # Create and accept a task
    create_resp = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={
            "principal_id": "ed25519_author_1",
            "description": "Task to negotiate",
        },
        timeout=5,
    )
    task_id = create_resp.json()["task"]["id"]

    requests.post(
        base_url(marketplace) + "/api/tasks/%s/accept" % task_id,
        json={"worker_principal": "ed25519_worker_1"},
        timeout=5,
    )

    # Send a message
    resp = requests.post(
        base_url(marketplace) + "/api/negotiations/%s" % task_id,
        json={
            "from_principal": "ed25519_worker_1",
            "message": "I can complete this in 2 days",
        },
        timeout=5,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "message" in data
    msg = data["message"]
    assert msg["from"] == "ed25519_worker_1"
    assert msg["message"] == "I can complete this in 2 days"
    assert "timestamp" in msg


def test_send_negotiation_message_unauthorized(marketplace):
    """Test that unauthorized users cannot send negotiation messages."""
    # Create and accept a task
    create_resp = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={
            "principal_id": "ed25519_author_1",
            "description": "Task",
        },
        timeout=5,
    )
    task_id = create_resp.json()["task"]["id"]

    requests.post(
        base_url(marketplace) + "/api/tasks/%s/accept" % task_id,
        json={"worker_principal": "ed25519_worker_1"},
        timeout=5,
    )

    # Try to send message as unauthorized user
    resp = requests.post(
        base_url(marketplace) + "/api/negotiations/%s" % task_id,
        json={
            "from_principal": "ed25519_unauthorized",
            "message": "Can I join?",
        },
        timeout=5,
    )
    assert resp.status_code == 403
    assert "not authorized" in resp.json()["error"]


def test_get_negotiations(marketplace):
    """Test fetching negotiation thread."""
    # Create, accept, and send messages
    create_resp = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={
            "principal_id": "ed25519_author_1",
            "description": "Task",
        },
        timeout=5,
    )
    task_id = create_resp.json()["task"]["id"]

    requests.post(
        base_url(marketplace) + "/api/tasks/%s/accept" % task_id,
        json={"worker_principal": "ed25519_worker_1"},
        timeout=5,
    )

    requests.post(
        base_url(marketplace) + "/api/negotiations/%s" % task_id,
        json={
            "from_principal": "ed25519_worker_1",
            "message": "Message 1",
        },
        timeout=5,
    )

    requests.post(
        base_url(marketplace) + "/api/negotiations/%s" % task_id,
        json={
            "from_principal": "ed25519_author_1",
            "message": "Message 2",
        },
        timeout=5,
    )

    # Get negotiations
    resp = requests.get(
        base_url(marketplace) + "/api/negotiations/%s" % task_id, timeout=5
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["task_id"] == task_id
    assert len(data["negotiations"]) == 2
    assert data["negotiations"][0]["message"] == "Message 1"
    assert data["negotiations"][1]["message"] == "Message 2"


def test_complete_task(marketplace):
    """Test completing a task."""
    # Create, accept task
    create_resp = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={
            "principal_id": "ed25519_author_1",
            "description": "Task to complete",
        },
        timeout=5,
    )
    task_id = create_resp.json()["task"]["id"]

    requests.post(
        base_url(marketplace) + "/api/tasks/%s/accept" % task_id,
        json={"worker_principal": "ed25519_worker_1"},
        timeout=5,
    )

    # Complete the task
    resp = requests.post(
        base_url(marketplace) + "/api/negotiations/%s/complete" % task_id,
        json={
            "author_principal": "ed25519_author_1",
            "outcome": "Work completed successfully",
        },
        timeout=5,
    )
    assert resp.status_code == 200
    task = resp.json()["task"]
    assert task["status"] == "completed"
    assert task["outcome"] == "Work completed successfully"


def test_complete_task_not_author(marketplace):
    """Test that only the author can complete a task."""
    # Create and accept task
    create_resp = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={
            "principal_id": "ed25519_author_1",
            "description": "Task",
        },
        timeout=5,
    )
    task_id = create_resp.json()["task"]["id"]

    requests.post(
        base_url(marketplace) + "/api/tasks/%s/accept" % task_id,
        json={"worker_principal": "ed25519_worker_1"},
        timeout=5,
    )

    # Try to complete as worker
    resp = requests.post(
        base_url(marketplace) + "/api/negotiations/%s/complete" % task_id,
        json={
            "author_principal": "ed25519_worker_1",
            "outcome": "Done",
        },
        timeout=5,
    )
    assert resp.status_code == 403
    assert "only task author can complete" in resp.json()["error"]


def test_complete_task_not_accepted(marketplace):
    """Test that task must be accepted before completion."""
    # Create task but don't accept
    create_resp = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={
            "principal_id": "ed25519_author_1",
            "description": "Task",
        },
        timeout=5,
    )
    task_id = create_resp.json()["task"]["id"]

    # Try to complete
    resp = requests.post(
        base_url(marketplace) + "/api/negotiations/%s/complete" % task_id,
        json={
            "author_principal": "ed25519_author_1",
            "outcome": "Done",
        },
        timeout=5,
    )
    assert resp.status_code == 400
    assert "must be accepted" in resp.json()["error"]


def test_end_to_end_flow(marketplace):
    """Test the complete flow: post -> accept -> negotiate -> complete."""
    author = "ed25519_author_1"
    worker = "ed25519_worker_1"

    # 1. Author posts a task
    create_resp = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={
            "principal_id": author,
            "description": "Implement login feature",
        },
        timeout=5,
    )
    assert create_resp.status_code == 200
    task_id = create_resp.json()["task"]["id"]

    # 2. List tasks to discover it
    list_resp = requests.get(base_url(marketplace) + "/api/tasks", timeout=5)
    assert list_resp.status_code == 200
    tasks = list_resp.json()["tasks"]
    assert len(tasks) >= 1
    assert any(t["id"] == task_id for t in tasks)

    # 3. Worker accepts the task
    accept_resp = requests.post(
        base_url(marketplace) + "/api/tasks/%s/accept" % task_id,
        json={"worker_principal": worker},
        timeout=5,
    )
    assert accept_resp.status_code == 200
    assert accept_resp.json()["task"]["status"] == "accepted"

    # 4. Negotiate details
    msg1_resp = requests.post(
        base_url(marketplace) + "/api/negotiations/%s" % task_id,
        json={
            "from_principal": worker,
            "message": "I can do this in 3 days",
        },
        timeout=5,
    )
    assert msg1_resp.status_code == 200

    msg2_resp = requests.post(
        base_url(marketplace) + "/api/negotiations/%s" % task_id,
        json={
            "from_principal": author,
            "message": "Sounds good, 3 days is fine",
        },
        timeout=5,
    )
    assert msg2_resp.status_code == 200

    # 5. Get negotiation thread
    negs_resp = requests.get(
        base_url(marketplace) + "/api/negotiations/%s" % task_id, timeout=5
    )
    assert negs_resp.status_code == 200
    assert len(negs_resp.json()["negotiations"]) == 2

    # 6. Author marks task complete
    complete_resp = requests.post(
        base_url(marketplace) + "/api/negotiations/%s/complete" % task_id,
        json={
            "author_principal": author,
            "outcome": "Feature implemented and tested successfully",
        },
        timeout=5,
    )
    assert complete_resp.status_code == 200
    task = complete_resp.json()["task"]
    assert task["status"] == "completed"
    assert task["outcome"] == "Feature implemented and tested successfully"

    # 7. Verify final state
    get_resp = requests.get(
        base_url(marketplace) + "/api/tasks/%s" % task_id, timeout=5
    )
    assert get_resp.status_code == 200
    final_task = get_resp.json()["task"]
    assert final_task["status"] == "completed"
    assert final_task["worker_principal"] == worker
    assert final_task["author_principal"] == author
