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


# ===========================================================================
# U4: competitive negotiation
# ===========================================================================

from agents.provider import agent as provider_agent  # noqa: E402
from agents.provider.config import PricingConfig as ProviderPricing  # noqa: E402


def _rpc(url, payload):
    """Drive a provider as a raw A2A client (trust extension opted in)."""
    body = {
        "jsonrpc": "2.0",
        "id": "t-%s" % uuid.uuid4().hex,
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "messageId": "m",
                "role": "user",
                "parts": [{"kind": "data", "data": payload}],
            }
        },
    }
    return requests.post(
        url, json=body, headers={"A2A-Extensions": TRUST_EXTENSION_URI}, timeout=10
    ).json()


def _data(env):
    for part in env["result"]["parts"]:
        if part.get("kind") == "data":
            return part["data"]
    raise AssertionError("no data part: %r" % (env,))


# ---- winner-selection unit tests (no HTTP) --------------------------------


def _offer(price, proven=True, rate=1.0, index=0, principal="p"):
    return {
        "price": price,
        "proven": proven,
        "verification_rate": rate,
        "index": index,
        "principal_id": principal,
        "task_id": "t-%s" % principal,
        "provider_url": "http://x",
    }


def test_select_winner_picks_cheapest():
    offers = [_offer(9, index=0, principal="a"), _offer(4, index=1, principal="b")]
    assert RequesterAgent._select_winner(offers)["principal_id"] == "b"


def test_select_winner_prefers_proven_over_cheaper_unproven():
    offers = [
        _offer(3, proven=False, rate=None, index=0, principal="cheap-unproven"),
        _offer(6, proven=True, rate=1.0, index=1, principal="proven"),
    ]
    # The cheaper one is unproven; a proven provider wins despite costing more.
    assert RequesterAgent._select_winner(offers)["principal_id"] == "proven"


def test_select_winner_tiebreak_by_reputation_then_order():
    offers = [
        _offer(5, rate=0.8, index=0, principal="lo-rep"),
        _offer(5, rate=0.99, index=1, principal="hi-rep"),
        _offer(5, rate=0.99, index=2, principal="hi-rep-later"),
    ]
    # Same price -> higher verification_rate wins; then earliest discovery.
    assert RequesterAgent._select_winner(offers)["principal_id"] == "hi-rep"


def test_competition_config_validation():
    with pytest.raises(ValueError):
        RequesterConfig(registry_url="http://x", fan_out=0)
    with pytest.raises(ValueError):
        RequesterConfig(registry_url="http://x", counter_fraction=1.5)


# ---- integration: a real multi-provider competitive stack -----------------


class CompetitiveStack(object):
    def __init__(self, registry_url, verification_url, api_key, tmp_path):
        self.registry_url = registry_url
        self.verification_url = verification_url
        self.api_key = api_key
        self.tmp_path = tmp_path
        self.providers = []
        self._n = 0

    def add_provider(self, list_price, min_price):
        self._n += 1
        p = provider_agent.make_server(
            port=0,
            verification_url=self.verification_url,
            registry_url=self.registry_url,
            api_key=self.api_key,
            keys_dir=str(self.tmp_path / ("keys-%d" % self._n)),
            pricing=ProviderPricing(list_price=list_price, min_price=min_price),
        )
        assert p.agent.register_with_registry()
        start_server(p)
        self.providers.append(p)
        return p

    def drive_one_verified_task(self, provider):
        """Run request->accept against a provider so it earns reputation."""
        url = base_url(provider)
        offer = _data(
            _rpc(
                url,
                {
                    "type": "task.request",
                    "input": {"containers": 2, "load_balancer": "alb"},
                },
            )
        )
        _rpc(url, {"type": "task.accept", "task_id": offer["task_id"]})


@pytest.fixture
def competitive_stack(tmp_path):
    verification = make_verification_server(port=0)
    start_server(verification)
    verification_url = base_url(verification)
    registry = make_registry_server(port=0, verification_url=verification_url)
    start_server(registry)
    registry_url = base_url(registry)
    api_key = requests.post(
        registry_url + "/admin/api-keys", timeout=5
    ).json()["api_key"]
    stack = CompetitiveStack(registry_url, verification_url, api_key, tmp_path)
    try:
        yield stack
    finally:
        for p in stack.providers:
            p.shutdown()
            p.server_close()
        for server in (registry, verification):
            server.shutdown()
            server.server_close()


def test_competitive_picks_cheapest_and_verifies(competitive_stack):
    competitive_stack.add_provider(list_price=9.0, min_price=8.0)  # pricey
    cheap = competitive_stack.add_provider(list_price=4.0, min_price=2.0)

    agent = RequesterAgent(make_config(competitive_stack.registry_url))
    outcome = agent.run_competitive()

    assert outcome["status"] == "verified", outcome
    assert outcome["offers_considered"] == 2
    assert outcome["provider_principal_id"] == cheap.agent.principal_id
    # Counter round pushed the cheap provider below its 4.0 list price
    # (0.9 * 4.0 = 3.6, still >= its 2.0 floor, so it accepts).
    assert outcome["price_paid"] == 3.6
    assert 'resource "aws_lb"' in outcome["artifacts"]["main.tf"]


def test_counter_below_floor_is_held_expensive_rival_can_win(competitive_stack):
    # Cheap provider has a HIGH floor: 0.9*5=4.5 < 4.9 floor -> it holds at 5.
    # The rival's counter 0.9*6=5.4 >= 5.0 floor -> it drops to 5.4... still
    # pricier. Cheapest standing price wins.
    competitive_stack.add_provider(list_price=5.0, min_price=4.9)  # holds at 5.0
    competitive_stack.add_provider(list_price=6.0, min_price=5.0)  # drops to 5.4
    agent = RequesterAgent(make_config(competitive_stack.registry_url))
    outcome = agent.run_competitive()
    assert outcome["status"] == "verified"
    assert outcome["price_paid"] == 5.0  # the held price beat the 5.4 concession


def test_reputation_floor_excludes_cheaper_unproven(competitive_stack):
    cheap = competitive_stack.add_provider(list_price=3.0, min_price=1.0)
    proven = competitive_stack.add_provider(list_price=9.0, min_price=5.0)
    # Give only the pricey provider a verified history.
    competitive_stack.drive_one_verified_task(proven)

    agent = RequesterAgent(
        make_config(competitive_stack.registry_url, min_reputation=0.9)
    )
    outcome = agent.run_competitive()

    # The cheaper provider has no reputation, so the floor excludes it: only
    # the proven (pricier) one is even considered.
    assert outcome["status"] == "verified"
    assert outcome["offers_considered"] == 1
    assert outcome["provider_principal_id"] == proven.agent.principal_id
    assert outcome["provider_principal_id"] != cheap.agent.principal_id


def test_competitive_no_candidates_when_none_clear_floor(competitive_stack):
    competitive_stack.add_provider(list_price=3.0, min_price=1.0)  # no history
    agent = RequesterAgent(
        make_config(competitive_stack.registry_url, min_reputation=0.9)
    )
    outcome = agent.run_competitive()
    assert outcome["status"] == "no_candidates"


# ---- F2: the final accept to the winner must not raise -----------------------


class _AcceptFailsProvider(ThreadingHTTPServer):
    """Offers and counters fine, but returns HTTP 500 on task.accept."""

    daemon_threads = True

    def __init__(self, principal_id):
        self.principal_id = principal_id
        super(_AcceptFailsProvider, self).__init__(("127.0.0.1", 0), _AFHandler)
        self.stub = self

    def card(self):
        return {
            "name": "flaky",
            "url": base_url(self),
            "version": "0.1.0",
            "protocolVersion": "0.3.0",
            "capabilities": {
                "extensions": [{"uri": TRUST_EXTENSION_URI, "required": False}]
            },
            "skills": [{"id": CAPABILITY_ID, "name": CAPABILITY_ID}],
        }


class _AFHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, status, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/.well-known/agent-card.json":
            self._json(200, self.server.card())
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        req_id = body.get("id")
        kind = body["params"]["message"]["parts"][0]["data"].get("type")
        if kind == "task.accept":
            self._json(500, {"error": "boom"})  # -> raise_for_status in _send
            return
        offer = {
            "type": "task.offer",
            "task_id": "task-af",
            "capability_id": CAPABILITY_ID,
            "price": 5.0,
            "currency": "USD",
        }
        self._json(
            200,
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": _agent_message(offer),
            },
        )


def test_competitive_winner_unreachable_at_accept_is_provider_error(registry_only):
    registry_url, api_key = registry_only
    stub = _AcceptFailsProvider(principal_id="flaky")
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
    assert resp.status_code == 200
    try:
        outcome = RequesterAgent(make_config(registry_url)).run_competitive()
        # The 500 on accept raises inside _send; run_competitive must catch it
        # and map it to a clean provider_error, not propagate the exception.
        assert outcome["status"] == "provider_error", outcome
        assert outcome["verified"] is False
    finally:
        stub.shutdown()
        stub.server_close()


# ---- F3/F4: portfolio assurance, only from a trusted verifier ----------------


@pytest.fixture
def unwired_stack(tmp_path):
    """Verifier + a registry NOT wired to it (so registry reputation stays
    neutral/None), plus real providers. This isolates the portfolio path: a
    provider can have verified portfolio work at the verifier while the
    registry reports no reputation rate for it."""
    verification = make_verification_server(port=0)
    start_server(verification)
    verification_url = base_url(verification)
    registry = make_registry_server(port=0)  # NOT wired to verification
    start_server(registry)
    registry_url = base_url(registry)
    api_key = requests.post(
        registry_url + "/admin/api-keys", timeout=5
    ).json()["api_key"]
    stack = CompetitiveStack(registry_url, verification_url, api_key, tmp_path)
    try:
        yield stack
    finally:
        for p in stack.providers:
            p.shutdown()
            p.server_close()
        for server in (registry, verification):
            server.shutdown()
            server.server_close()


def test_portfolio_flips_winner_only_via_trusted_verifier(unwired_stack):
    cheap = unwired_stack.add_provider(list_price=3.0, min_price=1.0)  # no work
    pricey = unwired_stack.add_provider(list_price=8.0, min_price=2.0)
    # Give the pricey provider verified portfolio work at the verifier. The
    # registry is unwired, so BOTH still report rate None to the requester.
    unwired_stack.drive_one_verified_task(pricey)

    # With a TRUSTED verifier configured, the pricey provider's verified
    # portfolio makes it 'proven' and it wins over the cheaper, portfolio-less
    # rival — portfolio is decisive.
    trusting = RequesterAgent(
        make_config(unwired_stack.registry_url, verification_url=unwired_stack.verification_url)
    )
    out = trusting.run_competitive()
    assert out["status"] == "verified", out
    assert out["provider_principal_id"] == pricey.agent.principal_id

    # WITHOUT a trusted verifier, portfolio assurance is ignored (an attacker
    # could fake it), both are unproven, and the cheapest wins instead.
    untrusting = RequesterAgent(make_config(unwired_stack.registry_url))
    out2 = untrusting.run_competitive()
    assert out2["status"] == "verified", out2
    assert out2["provider_principal_id"] == cheap.agent.principal_id
