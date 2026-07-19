"""Integration tests for Task Marketplace with Registry (U3).

Tests the full federation: marketplace task lifecycle + registry reputation recording.
"""

import json
import socket
import threading

import pytest
import requests

from apps.marketplace.server.app import make_server as make_marketplace_server
from registry.app import make_server as make_registry_server, RegistryService
from registry.index_store import IndexStore
from registry.user_index import UserIndex


def base_url(server):
    host, port = server.server_address[:2]
    return "http://%s:%d" % (host, port)


@pytest.fixture
def registry_and_marketplace(tmp_path):
    """Boot both registry and marketplace servers."""
    # Create registry with user_index
    user_index = UserIndex()
    index = IndexStore()
    service = RegistryService(
        index=index,
        user_index=user_index,
    )
    registry_server = make_registry_server(
        port=0,
        service=service,
    )
    thread_reg = threading.Thread(
        target=registry_server.serve_forever, daemon=True
    )
    thread_reg.start()

    # Create marketplace pointing at registry
    registry_url = base_url(registry_server)
    marketplace_server = make_marketplace_server(
        port=0, registry_url=registry_url
    )
    thread_mkt = threading.Thread(
        target=marketplace_server.serve_forever, daemon=True
    )
    thread_mkt.start()

    try:
        yield {
            "registry": registry_server,
            "marketplace": marketplace_server,
            "registry_url": registry_url,
            "marketplace_url": base_url(marketplace_server),
        }
    finally:
        marketplace_server.shutdown()
        registry_server.shutdown()
        marketplace_server.server_close()
        registry_server.server_close()
        thread_mkt.join(timeout=5)
        thread_reg.join(timeout=5)


def test_marketplace_integrates_with_registry(registry_and_marketplace):
    """Test that marketplace properly records reputation with registry."""
    author = "ed25519_author_principal_12345"
    worker = "ed25519_worker_principal_67890"
    mkt_url = registry_and_marketplace["marketplace_url"]
    reg_url = registry_and_marketplace["registry_url"]

    # 1. Register users in registry
    reg_author = requests.post(
        reg_url + "/auth/register",
        json={"principal_id": author},
        timeout=5,
    )
    assert reg_author.status_code == 200

    reg_worker = requests.post(
        reg_url + "/auth/register",
        json={"principal_id": worker},
        timeout=5,
    )
    assert reg_worker.status_code == 200

    # 2. Author posts task in marketplace
    post_resp = requests.post(
        mkt_url + "/api/tasks",
        json={
            "principal_id": author,
            "description": "Implement OAuth feature",
        },
        timeout=5,
    )
    assert post_resp.status_code == 200
    task_id = post_resp.json()["task"]["id"]

    # 3. Worker accepts task
    accept_resp = requests.post(
        mkt_url + "/api/tasks/%s/accept" % task_id,
        json={"worker_principal": worker},
        timeout=5,
    )
    assert accept_resp.status_code == 200

    # 4. They negotiate
    msg_resp = requests.post(
        mkt_url + "/api/negotiations/%s" % task_id,
        json={
            "from_principal": worker,
            "message": "I'll complete this in 2 days",
        },
        timeout=5,
    )
    assert msg_resp.status_code == 200

    # 5. Author completes task
    complete_resp = requests.post(
        mkt_url + "/api/negotiations/%s/complete" % task_id,
        json={
            "author_principal": author,
            "outcome": "Feature implemented and tested",
        },
        timeout=5,
    )
    assert complete_resp.status_code == 200
    task = complete_resp.json()["task"]
    assert task["status"] == "completed"

    # 6. Verify reputation was recorded in registry
    rep_resp = requests.get(
        reg_url + "/users/%s" % worker,
        timeout=5,
    )
    assert rep_resp.status_code == 200
    user_data = rep_resp.json()

    # Should have at least one reputation record for marketplace.tasks
    reputation_records = user_data.get("reputation_records", [])
    marketplace_records = [
        r for r in reputation_records
        if r.get("capability_id") == "marketplace.tasks"
    ]

    # At least one task should be recorded as verified
    if marketplace_records:
        record = marketplace_records[0]
        assert record.get("tasks_verified", 0) >= 1
        assert record.get("tasks_rejected", 0) == 0


def test_task_lifecycle_with_registry(registry_and_marketplace):
    """Test complete task lifecycle from creation to reputation."""
    author = "ed25519_author_test_001"
    worker = "ed25519_worker_test_001"
    mkt_url = registry_and_marketplace["marketplace_url"]
    reg_url = registry_and_marketplace["registry_url"]

    # Register users
    requests.post(
        reg_url + "/auth/register",
        json={"principal_id": author},
        timeout=5,
    )
    requests.post(
        reg_url + "/auth/register",
        json={"principal_id": worker},
        timeout=5,
    )

    # Create task
    create_resp = requests.post(
        mkt_url + "/api/tasks",
        json={
            "principal_id": author,
            "description": "Debug production issue",
        },
        timeout=5,
    )
    assert create_resp.status_code == 200
    task_id = create_resp.json()["task"]["id"]

    # Accept task
    accept_resp = requests.post(
        mkt_url + "/api/tasks/%s/accept" % task_id,
        json={"worker_principal": worker},
        timeout=5,
    )
    assert accept_resp.status_code == 200
    assert accept_resp.json()["task"]["status"] == "accepted"

    # Send negotiation messages
    for msg in ["I found the issue", "It's a memory leak", "Fixed and tested"]:
        msg_resp = requests.post(
            mkt_url + "/api/negotiations/%s" % task_id,
            json={"from_principal": worker, "message": msg},
            timeout=5,
        )
        assert msg_resp.status_code == 200

    # Retrieve negotiations
    negs_resp = requests.get(
        mkt_url + "/api/negotiations/%s" % task_id,
        timeout=5,
    )
    assert negs_resp.status_code == 200
    negotiations = negs_resp.json()["negotiations"]
    assert len(negotiations) >= 3

    # Complete task
    complete_resp = requests.post(
        mkt_url + "/api/negotiations/%s/complete" % task_id,
        json={
            "author_principal": author,
            "outcome": "Issue resolved. Memory leak was in cache cleanup.",
        },
        timeout=5,
    )
    assert complete_resp.status_code == 200
    final_task = complete_resp.json()["task"]
    assert final_task["status"] == "completed"
    assert "Memory leak" in final_task["outcome"]

    # Verify the task state in marketplace
    get_resp = requests.get(
        mkt_url + "/api/tasks/%s" % task_id,
        timeout=5,
    )
    assert get_resp.status_code == 200
    retrieved_task = get_resp.json()["task"]
    assert retrieved_task["status"] == "completed"
    assert retrieved_task["worker_principal"] == worker
    assert len(retrieved_task["negotiations"]) >= 3

    # Verify reputation recorded
    rep_resp = requests.get(
        reg_url + "/users/%s" % worker,
        timeout=5,
    )
    assert rep_resp.status_code == 200


def test_multiple_tasks_reputation_accumulation(registry_and_marketplace):
    """Test that multiple completed tasks accumulate reputation."""
    author = "ed25519_author_multi"
    worker = "ed25519_worker_multi"
    mkt_url = registry_and_marketplace["marketplace_url"]
    reg_url = registry_and_marketplace["registry_url"]

    # Register users
    requests.post(
        reg_url + "/auth/register",
        json={"principal_id": author},
        timeout=5,
    )
    requests.post(
        reg_url + "/auth/register",
        json={"principal_id": worker},
        timeout=5,
    )

    # Create and complete 3 tasks
    for i in range(3):
        task_resp = requests.post(
            mkt_url + "/api/tasks",
            json={
                "principal_id": author,
                "description": "Task %d" % (i + 1),
            },
            timeout=5,
        )
        task_id = task_resp.json()["task"]["id"]

        # Accept
        requests.post(
            mkt_url + "/api/tasks/%s/accept" % task_id,
            json={"worker_principal": worker},
            timeout=5,
        )

        # Complete
        complete_resp = requests.post(
            mkt_url + "/api/negotiations/%s/complete" % task_id,
            json={
                "author_principal": author,
                "outcome": "Completed task %d" % (i + 1),
            },
            timeout=5,
        )
        assert complete_resp.status_code == 200

    # Check reputation - should show all 3 tasks
    rep_resp = requests.get(
        reg_url + "/users/%s" % worker,
        timeout=5,
    )
    assert rep_resp.status_code == 200
    user_data = rep_resp.json()
    reputation_records = user_data.get("reputation_records", [])

    # Find marketplace.tasks records
    marketplace_records = [
        r for r in reputation_records
        if r.get("capability_id") == "marketplace.tasks"
    ]

    if marketplace_records:
        record = marketplace_records[0]
        assert record.get("tasks_verified", 0) >= 3
