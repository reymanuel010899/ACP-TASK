"""HTTP-level tests for the RFC-0002 Offer/CounterOffer P2P adoption (unit
U6): ``task.offer``/``task.counter`` dispatched through the pre-existing
``POST /p2p/request`` envelope -- see
``apps/marketplace/server/app.py``'s ``_p2p_task_offer``/
``_p2p_task_counter`` docstrings for the adoption decision.

No Registry is configured (``registry_url=None``), matching every other
P2P-standalone-mode test in this repo (e.g.
``tests/marketplace/test_marketplace_app.py``'s sibling suite) -- permission
checks are skipped entirely in that mode, isolating these tests to the
Offer/CounterOffer logic itself.
"""

import socket
import threading

import pytest
import requests

from apps.marketplace.server.app import make_server

TIMEOUT = 5.0


def _base_url(server):
    host, port = server.server_address[:2]
    return "http://%s:%d" % (host, port)


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


def _p2p(base_url, requester, request_type, input=None):  # noqa: A002
    return requests.post(
        "%s/p2p/request" % base_url,
        json={
            "requester_principal_id": requester,
            "request_type": request_type,
            "capability_id": "marketplace.tasks",
            "input": input if input is not None else {},
        },
        timeout=TIMEOUT,
    )


def _create_task(base_url, author, description):
    resp = requests.post(
        "%s/api/tasks" % base_url,
        json={"principal_id": author, "description": description},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["task"]


def test_task_offer_then_counter_round_trip(marketplace):
    base_url = _base_url(marketplace)
    task = _create_task(base_url, "user:author", "logo design")

    offer_resp = _p2p(
        base_url, "agent:designer", "task.offer",
        input={
            "type": "task.offer",
            "task_id": task["id"],
            "capability_id": "marketplace.tasks",
            "price": 200,
            "currency": "USD",
            "delivery": "3 days",
        },
    )
    assert offer_resp.status_code == 200, offer_resp.text
    offer = offer_resp.json()["result"]["offer"]
    assert offer["price"] == 200.0
    assert offer["provider_principal_id"] == "agent:designer"

    counter_resp = _p2p(
        base_url, "user:author", "task.counter",
        input={
            "type": "task.counter",
            "task_id": task["id"],
            "proposed_price": 150,
        },
    )
    assert counter_resp.status_code == 200, counter_resp.text
    counter = counter_resp.json()["result"]["counter_offer"]
    assert counter["proposed_price"] == 150.0


def test_task_offer_rejects_schema_invalid_payload(marketplace):
    base_url = _base_url(marketplace)
    task = _create_task(base_url, "user:author", "bad payload")

    # Missing required 'currency' (schemas/offer.schema.json).
    resp = _p2p(
        base_url, "agent:designer", "task.offer",
        input={
            "type": "task.offer",
            "task_id": task["id"],
            "capability_id": "marketplace.tasks",
            "price": 200,
        },
    )
    assert resp.status_code == 422, resp.text


def test_task_offer_rejects_leaked_reservation_field(marketplace):
    """additionalProperties: false on the Offer schema means a leaked
    reservation/floor field is a validation error by construction
    (RFC-0002 §6.4)."""
    base_url = _base_url(marketplace)
    task = _create_task(base_url, "user:author", "leaked reservation")

    resp = _p2p(
        base_url, "agent:designer", "task.offer",
        input={
            "type": "task.offer",
            "task_id": task["id"],
            "capability_id": "marketplace.tasks",
            "price": 200,
            "currency": "USD",
            "reservation_price": 50,
        },
    )
    assert resp.status_code == 422, resp.text


def test_task_counter_only_by_task_author(marketplace):
    base_url = _base_url(marketplace)
    task = _create_task(base_url, "user:author", "wrong counterer")
    _p2p(
        base_url, "agent:designer", "task.offer",
        input={
            "type": "task.offer",
            "task_id": task["id"],
            "capability_id": "marketplace.tasks",
            "price": 100,
            "currency": "USD",
        },
    )

    resp = _p2p(
        base_url, "user:someone-else", "task.counter",
        input={
            "type": "task.counter",
            "task_id": task["id"],
            "proposed_price": 50,
        },
    )
    assert resp.status_code == 403, resp.text


def test_task_counter_single_round_enforced(marketplace):
    base_url = _base_url(marketplace)
    task = _create_task(base_url, "user:author", "single round")
    _p2p(
        base_url, "agent:designer", "task.offer",
        input={
            "type": "task.offer",
            "task_id": task["id"],
            "capability_id": "marketplace.tasks",
            "price": 100,
            "currency": "USD",
        },
    )
    first = _p2p(
        base_url, "user:author", "task.counter",
        input={"type": "task.counter", "task_id": task["id"], "proposed_price": 80},
    )
    assert first.status_code == 200, first.text

    second = _p2p(
        base_url, "user:author", "task.counter",
        input={"type": "task.counter", "task_id": task["id"], "proposed_price": 70},
    )
    assert second.status_code == 400, second.text


def test_negotiations_endpoint_supports_pagination(marketplace):
    base_url = _base_url(marketplace)
    task = _create_task(base_url, "user:author", "paginated thread")
    requests.post(
        "%s/api/tasks/%s/accept" % (base_url, task["id"]),
        json={"worker_principal": "user:worker"},
        timeout=TIMEOUT,
    )
    for i in range(12):
        sender = "user:author" if i % 2 == 0 else "user:worker"
        resp = requests.post(
            "%s/api/negotiations/%s" % (base_url, task["id"]),
            json={"from_principal": sender, "message": "msg %d" % i},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text

    full = requests.get(
        "%s/api/negotiations/%s" % (base_url, task["id"]), timeout=TIMEOUT
    )
    assert len(full.json()["negotiations"]) == 12

    page = requests.get(
        "%s/api/negotiations/%s?skip=5&limit=5" % (base_url, task["id"]),
        timeout=TIMEOUT,
    )
    assert page.status_code == 200, page.text
    messages = page.json()["negotiations"]
    assert len(messages) == 5
    assert [m["message"] for m in messages] == [
        "msg %d" % i for i in range(5, 10)
    ]
