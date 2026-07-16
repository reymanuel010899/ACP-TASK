"""Tests for the MVP web console (unit W3).

Boots the whole web app (which boots the embedded demo stack: verification +
registry + 2 providers) and drives it over HTTP exactly as the browser would,
verifying the full consumer loop end to end: submit a task -> competitive
negotiation -> independent verification -> result rendered.
"""

import json
import threading

import pytest
import requests

from web.app import DEMO_PROVIDERS, make_server


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


def test_serves_the_page(console):
    resp = requests.get(base_url(console) + "/", timeout=5)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["Content-Type"]
    assert "AgentTrust" in resp.text
    assert "Buscar proveedor y ejecutar" in resp.text


def test_healthz(console):
    resp = requests.get(base_url(console) + "/healthz", timeout=5)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_task_runs_full_loop_and_returns_verified(console):
    resp = requests.post(
        base_url(console) + "/api/task",
        json={"containers": 2, "load_balancer": "alb"},
        timeout=30,
    )
    assert resp.status_code == 200
    outcome = resp.json()
    assert outcome["status"] == "verified", outcome
    assert outcome["verified"] is True
    assert outcome["evidence_status"] == "verified"
    # Competition happened and a fair price was paid.
    assert outcome["offers_considered"] == len(DEMO_PROVIDERS)
    assert isinstance(outcome["price_paid"], (int, float))
    # The winner is shown by its friendly name, not an opaque principal id.
    assert outcome["provider_name"] in {p["name"] for p in DEMO_PROVIDERS}
    # A real Terraform artifact came back.
    assert 'resource "aws_lb"' in outcome["artifacts"]["main.tf"]


def test_cheaper_provider_wins_the_competition(console):
    outcome = requests.post(
        base_url(console) + "/api/task",
        json={"containers": 1, "load_balancer": "alb"},
        timeout=30,
    ).json()
    # BudgetInfra (list 4) undercuts FastInfra (list 9); after the counter
    # round it should win.
    assert outcome["provider_name"] == "BudgetInfra"
    assert outcome["price_paid"] < 4.0  # counter pushed it below list


def test_invalid_task_is_rejected(console):
    resp = requests.post(
        base_url(console) + "/api/task",
        json={"containers": 0, "load_balancer": "alb"},
        timeout=5,
    )
    assert resp.status_code == 400

    resp = requests.post(
        base_url(console) + "/api/task",
        json={"containers": 2, "load_balancer": "nlb"},
        timeout=5,
    )
    assert resp.status_code == 400


def test_unknown_path_is_404(console):
    assert requests.get(base_url(console) + "/nope", timeout=5).status_code == 404
