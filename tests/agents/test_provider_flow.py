"""Tests for the AgentTrust Provider Agent (unit U6).

Test-first: these tests define the contract of ``agents.provider.agent``
and ``agents.provider.terraform_generate`` before the implementation exists.

The provider agent is a third-party-buildable A2A server: the agent code
itself MUST NOT import from ``services`` or ``registry`` (there is a guard
test for that). The *tests*, however, run the real U3 verification service
and U4 registry in-process on port 0 and drive the provider over HTTP as an
A2A client.

Covered plan scenarios:

- Happy path: a valid task request/accept flow produces a syntactically
  valid Terraform artifact and a ``verified`` Evidence submission, with
  A2A TaskState COMPLETED.
- Edge: malformed ``task.request`` (missing input) -> JSON-RPC -32602,
  no artifact produced.
- Integration: the artifact hash recorded in the Evidence matches sha256 of
  the artifact actually returned in ``task.result``.
- Graceful degradation: without the ``A2A-Extensions`` header the response
  carries NO trust metadata key.
- Resilience: with the verification service stopped, ``task.result`` comes
  back with ``evidence_status: "pending"`` (short timeout, no hang).
- Registration: on startup the provider appears in the registry's
  ``/search`` for ``terraform.generate``.
"""

import hashlib
import json
import re
import socket
import threading
import uuid
from pathlib import Path

import pytest
import requests

# Tests (and only tests) may import the reference services.
from registry.app import make_server as make_registry_server
from services.verification.app import make_server as make_verification_server

from agents.provider import agent as provider_agent
from agents.provider.agent import TRUST_EXTENSION_URI
from agents.provider.terraform_generate import (
    generate_terraform,
    validate_own_output,
)

CAPABILITY_ID = "terraform.generate"

AGENTS_DIR = Path(provider_agent.__file__).resolve().parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def start_server(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def base_url(server):
    host, port = server.server_address[:2]
    return "http://%s:%d" % (host, port)


def free_port():
    """A port with nothing listening on it (connection refused, instantly)."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def send_rpc(url, payload, opt_in=True, method="message/send", req_id=None):
    """Drive the provider as an A2A JSON-RPC client."""
    headers = {}
    if opt_in:
        headers["A2A-Extensions"] = TRUST_EXTENSION_URI
    body = {
        "jsonrpc": "2.0",
        "id": req_id if req_id is not None else "req-%s" % uuid.uuid4().hex,
        "method": method,
        "params": {
            "message": {
                "kind": "message",
                "messageId": "msg-%s" % uuid.uuid4().hex,
                "role": "user",
                "parts": [{"kind": "data", "data": payload}],
            }
        },
    }
    return requests.post(url, json=body, headers=headers, timeout=15)


def data_part(message):
    """The first ``data`` part of an A2A message."""
    for part in message["parts"]:
        if part.get("kind") == "data":
            return part["data"]
    raise AssertionError("no data part in message: %r" % (message,))


def run_task(url, opt_in=True, containers=2, load_balancer="alb"):
    """request -> offer -> accept -> result; returns the result message."""
    offer_resp = send_rpc(
        url,
        {
            "type": "task.request",
            "input": {"containers": containers, "load_balancer": load_balancer},
        },
        opt_in=opt_in,
    )
    assert offer_resp.status_code == 200
    offer_body = offer_resp.json()
    assert "error" not in offer_body, offer_body
    offer = data_part(offer_body["result"])
    assert offer["type"] == "task.offer"
    assert offer["task_id"]
    assert isinstance(offer.get("terms"), dict)

    accept_resp = send_rpc(
        url,
        {"type": "task.accept", "task_id": offer["task_id"]},
        opt_in=opt_in,
    )
    assert accept_resp.status_code == 200
    accept_body = accept_resp.json()
    assert "error" not in accept_body, accept_body
    return accept_body["result"], accept_resp


# ---------------------------------------------------------------------------
# Fixtures: real U3 + U4 in-process, provider pointed at them over HTTP
# ---------------------------------------------------------------------------


class Stack(object):
    def __init__(self, verification, registry, provider, api_key):
        self.verification = verification
        self.registry = registry
        self.provider = provider
        self.api_key = api_key
        self.verification_url = base_url(verification)
        self.registry_url = base_url(registry)
        self.provider_url = base_url(provider)


@pytest.fixture
def stack(tmp_path):
    verification = make_verification_server(port=0)
    start_server(verification)
    verification_url = base_url(verification)

    registry = make_registry_server(port=0, verification_url=verification_url)
    start_server(registry)
    registry_url = base_url(registry)

    api_key = requests.post(
        registry_url + "/admin/api-keys", timeout=5
    ).json()["api_key"]

    provider = provider_agent.make_server(
        port=0,
        verification_url=verification_url,
        registry_url=registry_url,
        api_key=api_key,
        keys_dir=str(tmp_path / "keys"),
    )
    assert provider.agent.register_with_registry()
    start_server(provider)

    yield Stack(verification, registry, provider, api_key)

    for server in (provider, registry, verification):
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# Hard constraint: independently buildable (no imports of services/registry)
# ---------------------------------------------------------------------------


FORBIDDEN_IMPORT_RE = re.compile(
    r"^\s*(from\s+(services|registry|agents\.requester)[.\s]"
    r"|import\s+(services|registry)\b)",
    re.MULTILINE,
)


def test_provider_code_does_not_import_reference_services():
    for path in AGENTS_DIR.rglob("*.py"):
        source = path.read_text()
        match = FORBIDDEN_IMPORT_RE.search(source)
        assert match is None, "%s imports a forbidden module: %r" % (
            path,
            match.group(0) if match else None,
        )


# ---------------------------------------------------------------------------
# Terraform generator unit tests
# ---------------------------------------------------------------------------


def test_generate_terraform_shape_and_self_check():
    hcl = generate_terraform(2, "alb")
    assert validate_own_output(hcl)
    assert 'resource "aws_lb"' in hcl
    assert 'resource "aws_lb_target_group"' in hcl
    assert 'resource "aws_lb_listener"' in hcl
    # Two containers behind the ALB.
    assert hcl.count('resource "aws_ecs_service"') == 2
    assert hcl.count('resource "aws_ecs_task_definition"') == 2
    # Balanced braces, sanity.
    assert hcl.count("{") == hcl.count("}")


def test_generate_terraform_rejects_bad_input():
    with pytest.raises(ValueError):
        generate_terraform(0, "alb")
    with pytest.raises(ValueError):
        generate_terraform(2, "nlb-from-mars")


def test_validate_own_output_rejects_broken_hcl():
    assert not validate_own_output("")
    assert not validate_own_output('resource "aws_lb" "x" {')
    assert not validate_own_output("just some prose, no resources")


# ---------------------------------------------------------------------------
# Agent Card
# ---------------------------------------------------------------------------


def test_agent_card_declares_skill_and_extension(stack):
    resp = requests.get(
        stack.provider_url + "/.well-known/agent-card.json", timeout=5
    )
    assert resp.status_code == 200
    card = resp.json()
    skill_ids = [skill["id"] for skill in card["skills"]]
    assert CAPABILITY_ID in skill_ids  # dot form, aligns with U3/U4
    extensions = card["capabilities"]["extensions"]
    trust = [e for e in extensions if e["uri"] == TRUST_EXTENSION_URI]
    assert len(trust) == 1
    params = trust[0]["params"]
    assert params["principal_id"] == stack.provider.agent.principal_id
    assert params["verification_service_url"] == stack.verification_url


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_verified_evidence_and_completed_task(stack):
    message, resp = run_task(stack.provider_url, opt_in=True)

    # A2A shape + TaskState COMPLETED.
    assert message["kind"] == "message"
    assert message["role"] == "agent"
    result = data_part(message)
    assert result["type"] == "task.result"
    assert result["task_state"] == "completed"

    # The artifact is syntactically valid Terraform.
    hcl = result["artifacts"]["main.tf"]
    assert validate_own_output(hcl)
    assert 'resource "aws_lb"' in hcl

    # Trust metadata: extension echoed, evidence verified by the real U3.
    assert TRUST_EXTENSION_URI in resp.headers.get("A2A-Extensions", "")
    assert TRUST_EXTENSION_URI in message["extensions"]
    trust = message["metadata"][TRUST_EXTENSION_URI]
    assert trust["evidence_status"] == "verified"
    evidence = trust["evidence"]
    assert evidence["capability_id"] == CAPABILITY_ID
    assert evidence["schema_valid"] is True
    assert evidence["tests_passed"] is True
    vr = trust["verification_result"]
    assert vr["verdict"] == "verified"
    assert vr["evidence_id"] == evidence["evidence_id"]

    # The verification service really recorded it (queryable over HTTP).
    lookup = requests.get(
        stack.verification_url
        + "/verification-results/%s" % evidence["evidence_id"],
        timeout=5,
    )
    assert lookup.status_code == 200
    assert lookup.json()["verification_result"]["verdict"] == "verified"


# ---------------------------------------------------------------------------
# Integration: evidence hash matches the returned artifact
# ---------------------------------------------------------------------------


def test_evidence_hash_matches_returned_artifact(stack):
    message, _ = run_task(stack.provider_url, opt_in=True)
    result = data_part(message)
    hcl = result["artifacts"]["main.tf"]
    trust = message["metadata"][TRUST_EXTENSION_URI]
    recorded = trust["evidence"]["artifact_hashes"]["main.tf"]
    assert recorded == hashlib.sha256(hcl.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Edge: malformed task.request -> JSON-RPC -32602, no artifact
# ---------------------------------------------------------------------------


def test_malformed_task_request_is_invalid_params(stack):
    resp = send_rpc(stack.provider_url, {"type": "task.request", "input": {}})
    body = resp.json()
    assert "result" not in body
    assert body["error"]["code"] == -32602

    # Missing input entirely.
    resp = send_rpc(stack.provider_url, {"type": "task.request"})
    assert resp.json()["error"]["code"] == -32602

    # Wrong types are invalid too, never a broken artifact.
    resp = send_rpc(
        stack.provider_url,
        {
            "type": "task.request",
            "input": {"containers": "two", "load_balancer": "alb"},
        },
    )
    assert resp.json()["error"]["code"] == -32602

    # And nothing was submitted to the verification service for it.
    resp = send_rpc(
        stack.provider_url,
        {"type": "task.accept", "task_id": "task-never-offered"},
    )
    assert resp.json()["error"]["code"] == -32602


def test_unknown_method_is_method_not_found(stack):
    resp = send_rpc(
        stack.provider_url, {"type": "task.request"}, method="message/stream"
    )
    assert resp.json()["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# Graceful degradation: no opt-in header -> plain A2A message, no trust keys
# ---------------------------------------------------------------------------


def test_no_optin_means_no_trust_metadata(stack):
    message, resp = run_task(stack.provider_url, opt_in=False)
    result = data_part(message)
    assert result["task_state"] == "completed"
    assert TRUST_EXTENSION_URI not in (message.get("metadata") or {})
    assert TRUST_EXTENSION_URI not in (message.get("extensions") or [])
    assert TRUST_EXTENSION_URI not in resp.headers.get("A2A-Extensions", "")


# ---------------------------------------------------------------------------
# Verification service unreachable -> evidence_status "pending", no hang
# ---------------------------------------------------------------------------


def test_unreachable_verifier_yields_pending(tmp_path):
    dead_url = "http://127.0.0.1:%d" % free_port()
    provider = provider_agent.make_server(
        port=0,
        verification_url=dead_url,
        keys_dir=str(tmp_path / "keys"),
    )
    start_server(provider)
    try:
        message, _ = run_task(base_url(provider), opt_in=True)
        result = data_part(message)
        assert result["task_state"] == "completed"
        trust = message["metadata"][TRUST_EXTENSION_URI]
        assert trust["evidence_status"] == "pending"
        # The evidence itself is still included; no verification_result yet.
        assert trust["evidence"]["capability_id"] == CAPABILITY_ID
        assert "verification_result" not in trust
    finally:
        provider.shutdown()
        provider.server_close()


# ---------------------------------------------------------------------------
# Registration: provider shows up in registry search on startup
# ---------------------------------------------------------------------------


def test_provider_registered_and_searchable(stack):
    resp = requests.get(
        stack.registry_url + "/search",
        params={"capability": CAPABILITY_ID},
        timeout=5,
    )
    assert resp.status_code == 200
    candidates = resp.json()["candidates"]
    principal_ids = [c["principal_id"] for c in candidates]
    assert stack.provider.agent.principal_id in principal_ids


def test_reputation_visible_in_registry_after_verified_task(stack):
    run_task(stack.provider_url, opt_in=True)
    resp = requests.get(
        stack.registry_url + "/search",
        params={"capability": CAPABILITY_ID, "min_reputation": "0.9"},
        timeout=5,
    )
    candidates = resp.json()["candidates"]
    match = [
        c
        for c in candidates
        if c["principal_id"] == stack.provider.agent.principal_id
    ]
    assert len(match) == 1
    summary = match[0]["reputation_summary"]
    assert summary["tasks_verified"] >= 1
    assert summary["verification_rate"] == 1.0


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------


def test_keypair_persists_across_restarts(tmp_path):
    keys_dir = tmp_path / "keys"
    first = provider_agent.load_or_create_keypair(str(keys_dir))
    second = provider_agent.load_or_create_keypair(str(keys_dir))
    assert bytes(first.verify_key) == bytes(second.verify_key)
    # The key material dir is gitignore-safe.
    assert (keys_dir / ".gitignore").read_text().strip() == "*"


def test_session_signature_is_canonical_and_valid(tmp_path):
    """The provider signs sessions in the RFC-0001 canonical form."""
    import base64

    from nacl.signing import VerifyKey

    provider = provider_agent.make_server(
        port=0,
        verification_url="http://127.0.0.1:1",
        keys_dir=str(tmp_path / "keys"),
    )
    try:
        agent = provider.agent
        session = agent.new_session()
        claims = json.dumps(
            {
                "expires_at": session["expires_at"],
                "principal_id": session["principal_id"],
                "session_id": session["session_id"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        public_key = base64.b64decode(agent.principal["public_key"])
        signature = base64.b64decode(session["principal_signature"])
        VerifyKey(public_key).verify(claims, signature)  # raises if invalid
    finally:
        provider.server_close()
