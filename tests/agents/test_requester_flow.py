"""Tests for the AgentTrust Requester Agent (unit U5).

The requester is a third-party-buildable A2A *client*: its code MUST NOT
import from ``services``, ``registry``, or ``agents.provider`` (guard test
below). The *tests* may run the real U3 verification service, U4 registry,
and U6 provider in-process on port 0 to exercise the true ``verified`` path,
and use a small stub provider to drive the outcome branches the demo
provider never produces on its own (rejected / unverified / A2A failure).

Covered plan scenarios:

- Happy path: with a provider and registry running, the requester completes
  search -> request -> accept -> result and reports a ``verified`` result.
- Edge: a ``task.result`` whose ``evidence_status`` is ``rejected`` is
  treated as NOT complete, and distinct from an A2A-level ``failed``.
- Error path: no matching candidates yields a clear ``no_candidates``
  outcome, not an unhandled exception.
"""

import json
import re
import socket
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import requests

# Tests (and only tests) may import the reference services.
from registry.app import make_server as make_registry_server
from services.verification.app import make_server as make_verification_server
from agents.provider import agent as provider_agent

from agents.requester import agent as requester_agent
from agents.requester.agent import RequesterAgent, TRUST_EXTENSION_URI
from agents.requester.config import RequesterConfig

CAPABILITY_ID = "terraform.generate"

REQUESTER_DIR = Path(requester_agent.__file__).resolve().parent


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


def make_config(registry_url, **kw):
    kw.setdefault("http_timeout", 5.0)
    return RequesterConfig(registry_url=registry_url, **kw)


# ---------------------------------------------------------------------------
# Live stack: real U3 + U4 + U6, so the requester's `verified` path is genuine
# ---------------------------------------------------------------------------


class LiveStack(object):
    def __init__(self, registry_url, verification_url, provider, api_key):
        self.registry_url = registry_url
        self.verification_url = verification_url
        self.provider = provider
        self.api_key = api_key
        self.provider_principal_id = provider.agent.principal_id


@pytest.fixture
def live_stack(tmp_path):
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

    yield LiveStack(registry_url, verification_url, provider, api_key)

    for server in (provider, registry, verification):
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# Stub provider: fabricated A2A responses for the non-verified branches
# ---------------------------------------------------------------------------


class _StubHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # noqa: A002
        pass

    @property
    def stub(self):
        return self.server.stub

    def _json(self, status, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/.well-known/agent-card.json":
            self._json(200, self.stub.card())
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        self.stub.seen_extensions_header = self.headers.get("A2A-Extensions")
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        req_id = body.get("id")
        data = body["params"]["message"]["parts"][0]["data"]
        kind = data.get("type")
        if kind == "task.request":
            self._json(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": _agent_message(
                        {
                            "type": "task.offer",
                            "task_id": "task-stub",
                            "capability_id": self.stub.capability,
                            "terms": {"price": "0"},
                        }
                    ),
                },
            )
        elif kind == "task.accept":
            self._json(200, self.stub.accept_envelope(req_id))
        else:
            self._json(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "bad type"},
                },
            )


def _agent_message(data, trust=None):
    message = {
        "kind": "message",
        "messageId": "msg-%s" % uuid.uuid4().hex,
        "role": "agent",
        "parts": [{"kind": "data", "data": data}],
    }
    if trust is not None:
        message["extensions"] = [TRUST_EXTENSION_URI]
        message["metadata"] = {TRUST_EXTENSION_URI: trust}
    return message


class StubProvider(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        principal_id,
        capability=CAPABILITY_ID,
        task_state="completed",
        evidence_status="verified",
        include_trust=True,
        accept_error=None,
    ):
        self.principal_id = principal_id
        self.capability = capability
        self.task_state = task_state
        self.evidence_status = evidence_status
        self.include_trust = include_trust
        self.accept_error = accept_error
        self.seen_extensions_header = None
        super(StubProvider, self).__init__(("127.0.0.1", 0), _StubHandler)
        self.stub = self

    def card(self):
        return {
            "name": "stub",
            "url": base_url(self),
            "version": "0.1.0",
            "protocolVersion": "0.3.0",
            "capabilities": {
                "extensions": [{"uri": TRUST_EXTENSION_URI, "required": False}]
            },
            "skills": [{"id": self.capability, "name": self.capability}],
        }

    def accept_envelope(self, req_id):
        if self.accept_error is not None:
            return {"jsonrpc": "2.0", "id": req_id, "error": self.accept_error}
        result = {
            "type": "task.result",
            "task_id": "task-stub",
            "task_state": self.task_state,
            "artifacts": {"main.tf": "# stub artifact"},
        }
        trust = None
        if self.include_trust:
            trust = {"evidence_status": self.evidence_status}
            if self.evidence_status in ("verified", "rejected"):
                trust["verification_result"] = {
                    "verdict": self.evidence_status,
                    "evidence_id": "ev-stub",
                }
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": _agent_message(result, trust=trust),
        }


def register_stub(registry_url, api_key, stub):
    start_server(stub)
    resp = requests.post(
        registry_url + "/register",
        json={
            "agent_card": stub.card(),
            "principal_id": stub.principal_id,
            "api_key": api_key,
        },
        timeout=5,
    )
    assert resp.status_code == 200, resp.text


@pytest.fixture
def registry_only():
    """A bare registry (no verification wiring) plus a fresh api key."""
    registry = make_registry_server(port=0)
    start_server(registry)
    registry_url = base_url(registry)
    api_key = requests.post(
        registry_url + "/admin/api-keys", timeout=5
    ).json()["api_key"]
    yield registry_url, api_key
    registry.shutdown()
    registry.server_close()


# ---------------------------------------------------------------------------
# Hard constraint: independently buildable (no imports of the reference impls)
# ---------------------------------------------------------------------------


FORBIDDEN_IMPORT_RE = re.compile(
    r"^\s*(from\s+(services|registry|agents\.provider)[.\s]"
    r"|import\s+(services|registry|agents\.provider)\b)",
    re.MULTILINE,
)


def test_requester_code_does_not_import_reference_impls():
    for path in REQUESTER_DIR.rglob("*.py"):
        source = path.read_text()
        match = FORBIDDEN_IMPORT_RE.search(source)
        assert match is None, "%s imports a forbidden module: %r" % (
            path,
            match.group(0) if match else None,
        )


# ---------------------------------------------------------------------------
# Config: registry URL is required (KTD5)
# ---------------------------------------------------------------------------


def test_registry_url_is_required():
    with pytest.raises(ValueError):
        RequesterConfig(registry_url="")


# ---------------------------------------------------------------------------
# select(): prefer proven reputation, tolerate neutral/missing
# ---------------------------------------------------------------------------


def test_select_prefers_higher_verification_rate():
    candidates = [
        {"principal_id": "a", "reputation_summary": {"verification_rate": 0.5}},
        {"principal_id": "b", "reputation_summary": {"verification_rate": 0.9}},
        {"principal_id": "c", "reputation_summary": {"verification_rate": None}},
    ]
    assert RequesterAgent.select(candidates)["principal_id"] == "b"


def test_select_none_when_empty():
    assert RequesterAgent.select([]) is None


# ---------------------------------------------------------------------------
# Happy path against the real U3 + U4 + U6 stack -> genuinely `verified`
# ---------------------------------------------------------------------------


def test_happy_path_reports_verified(live_stack):
    agent = RequesterAgent(make_config(live_stack.registry_url))
    outcome = agent.run()

    assert outcome["status"] == "verified"
    assert outcome["verified"] is True
    assert outcome["provider_principal_id"] == live_stack.provider_principal_id
    assert outcome["task_state"] == "completed"
    assert outcome["evidence_status"] == "verified"
    assert outcome["verification_result"]["verdict"] == "verified"
    # A real Terraform artifact came back.
    assert 'resource "aws_lb"' in outcome["artifacts"]["main.tf"]


# ---------------------------------------------------------------------------
# Error path: no candidates -> clear outcome, not an exception
# ---------------------------------------------------------------------------


def test_no_candidates_for_unknown_capability(live_stack):
    agent = RequesterAgent(make_config(live_stack.registry_url))
    outcome = agent.run(capability="video.transcode")
    assert outcome["status"] == "no_candidates"
    assert outcome["verified"] is False
    assert "video.transcode" in outcome["reason"]


def test_no_candidates_below_reputation_threshold(registry_only):
    registry_url, api_key = registry_only
    # A provider with no history: neutral reputation does not pass a threshold.
    register_stub(registry_url, api_key, StubProvider(principal_id="fresh"))
    agent = RequesterAgent(make_config(registry_url, min_reputation=0.9))
    outcome = agent.run()
    assert outcome["status"] == "no_candidates"


def test_registry_unreachable_is_a_clean_outcome():
    dead = "http://127.0.0.1:%d" % free_port()
    agent = RequesterAgent(make_config(dead))
    outcome = agent.run()
    assert outcome["status"] == "registry_unreachable"
    assert outcome["verified"] is False


# ---------------------------------------------------------------------------
# Edge: evidence_status `rejected` is NOT complete and distinct from `failed`
# ---------------------------------------------------------------------------


def test_rejected_evidence_is_not_verified(registry_only):
    registry_url, api_key = registry_only
    register_stub(
        registry_url,
        api_key,
        StubProvider(
            principal_id="rejecter",
            task_state="completed",
            evidence_status="rejected",
        ),
    )
    outcome = RequesterAgent(make_config(registry_url)).run()
    assert outcome["status"] == "rejected"
    assert outcome["verified"] is False
    assert outcome["task_state"] == "completed"  # A2A said done...
    assert outcome["evidence_status"] == "rejected"  # ...verification disagreed


def test_a2a_failed_is_provider_error_distinct_from_rejected(registry_only):
    registry_url, api_key = registry_only
    register_stub(
        registry_url,
        api_key,
        StubProvider(
            principal_id="failer",
            task_state="failed",
            include_trust=False,
        ),
    )
    outcome = RequesterAgent(make_config(registry_url)).run()
    assert outcome["status"] == "provider_error"
    assert outcome["status"] != "rejected"
    assert outcome["verified"] is False


def test_completed_without_verification_is_unverified(registry_only):
    registry_url, api_key = registry_only
    register_stub(
        registry_url,
        api_key,
        StubProvider(
            principal_id="pending",
            task_state="completed",
            evidence_status="pending",
        ),
    )
    outcome = RequesterAgent(make_config(registry_url)).run()
    assert outcome["status"] == "unverified"
    assert outcome["verified"] is False


def test_provider_rpc_error_on_accept_is_provider_error(registry_only):
    registry_url, api_key = registry_only
    register_stub(
        registry_url,
        api_key,
        StubProvider(
            principal_id="grumpy",
            accept_error={"code": -32602, "message": "nope"},
        ),
    )
    outcome = RequesterAgent(make_config(registry_url)).run()
    assert outcome["status"] == "provider_error"


# ---------------------------------------------------------------------------
# The requester opts in to the trust layer (A2A-Extensions header)
# ---------------------------------------------------------------------------


def test_requester_opts_into_trust_extension(registry_only):
    registry_url, api_key = registry_only
    stub = StubProvider(principal_id="listener")
    register_stub(registry_url, api_key, stub)
    RequesterAgent(make_config(registry_url)).run()
    assert stub.seen_extensions_header == TRUST_EXTENSION_URI
