"""Tests for the MVP web console (unit W3).

Boots the whole web app (which boots the embedded demo stack: verification +
registry + 2 providers) and drives it over HTTP exactly as the browser would,
verifying the full consumer loop end to end: submit a task -> competitive
negotiation -> independent verification -> result rendered.
"""

import json
import socket
import threading

import pytest
import requests

from agents.provider import agent as provider_agent
from agents.provider.config import PricingConfig
from web.app import DEMO_PROVIDERS, _inspect_card, make_server

TRUST_URI = provider_agent.TRUST_EXTENSION_URI


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
    assert "Pedirlo a mi agente" in resp.text
    assert "¿Qué necesitás?" in resp.text


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


def test_task_via_natural_language(console):
    # The consumer path: free text -> the agent interprets and runs it.
    resp = requests.post(
        base_url(console) + "/api/task",
        json={"text": "necesito infra para una app web con 3 contenedores"},
        timeout=30,
    )
    assert resp.status_code == 200
    outcome = resp.json()
    assert outcome["status"] == "verified", outcome
    # The agent echoes what it understood, and it built the 3-container task.
    assert "3" in outcome["interpretation"]
    assert outcome["artifacts"]["main.tf"].count('resource "aws_ecs_service"') == 3


def test_non_infra_text_is_declined(console):
    resp = requests.post(
        base_url(console) + "/api/task",
        json={"text": "editame este video para instagram"},
        timeout=10,
    )
    assert resp.status_code == 400
    assert "terraform" in resp.json()["error"].lower() or "infra" in resp.json()["error"].lower()


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


# ---- self-registration by Agent Card URL (no CLI) ---------------------------


def test_register_provider_by_url_and_it_competes(console, tmp_path):
    stack = console.stack
    # A real provider on the same embedded stack (so it can submit evidence),
    # NOT pre-registered — the web form does the registration.
    prov = provider_agent.make_server(
        port=0,
        verification_url=stack.verification_url,
        keys_dir=str(tmp_path / "extkeys"),
        pricing=PricingConfig(list_price=2.0, min_price=1.0),  # cheapest
    )
    threading.Thread(target=prov.serve_forever, daemon=True).start()
    try:
        resp = requests.post(
            base_url(console) + "/api/register-provider",
            json={"url": base_url(prov)},
            timeout=10,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["registered"] is True
        assert "terraform.generate" in body["capabilities"]

        # It now appears in the running registry's capability search.
        search = requests.get(
            stack.registry_url + "/search",
            params={"capability": "terraform.generate"},
            timeout=5,
        ).json()
        assert prov.agent.principal_id in [
            c["principal_id"] for c in search["candidates"]
        ]

        # And it competes in the next task: 3 providers now, and the newcomer
        # (cheapest) wins verified.
        outcome = requests.post(
            base_url(console) + "/api/task",
            json={"text": "infra con 2 contenedores"},
            timeout=30,
        ).json()
        assert outcome["status"] == "verified"
        assert outcome["offers_considered"] == 3
        assert outcome["provider_principal_id"] == prov.agent.principal_id
    finally:
        prov.shutdown()
        prov.server_close()


def test_register_provider_unreachable_url_is_400(console):
    resp = requests.post(
        base_url(console) + "/api/register-provider",
        json={"url": "http://127.0.0.1:%d" % free_port()},
        timeout=5,
    )
    assert resp.status_code == 400
    assert "alcanzar" in resp.json()["error"].lower()


def test_inspect_card_rejects_missing_trust_extension():
    pid, caps, err = _inspect_card(
        {"skills": [{"id": "x"}], "capabilities": {"extensions": []}}
    )
    assert pid is None
    assert "confianza" in err.lower()


def test_inspect_card_rejects_no_skills():
    card = {
        "capabilities": {
            "extensions": [{"uri": TRUST_URI, "params": {"principal_id": "p1"}}]
        },
        "skills": [],
    }
    pid, caps, err = _inspect_card(card)
    assert pid is None
    assert "capacidad" in err.lower() or "skill" in err.lower()


def test_inspect_card_accepts_valid_card():
    card = {
        "capabilities": {
            "extensions": [{"uri": TRUST_URI, "params": {"principal_id": "p1"}}]
        },
        "skills": [{"id": "terraform.generate"}],
    }
    pid, caps, err = _inspect_card(card)
    assert err is None
    assert pid == "p1"
    assert caps == ["terraform.generate"]
