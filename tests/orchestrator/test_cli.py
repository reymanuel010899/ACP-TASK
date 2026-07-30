"""Tests for the orchestrator CLI entry point (unit U25).

The CLI is thin glue: argument parsing, a clarification/REPL loop, and
rendering. Tests inject a fake agent through ``main(agent_factory=...)``
for the conversation-shape tests, and drive the REAL ``build_agent``
wiring (RuleBrain + SpendPolicy + ApprovalGate + cli_prompt_callback)
with fake tools/stdin for the approval and no-API-key tests. No network:
registry URLs point at a closed local port and ``register()`` degrades
to a warning.

U7 adds a real signature-enforcing marketplace stack (mirroring
``tests/integration/test_secure_mode_end_to_end.py``'s ephemeral-server
fixture pattern) so the ``--require-signatures`` wiring is proven against
an actual signed round trip -- not merely a ``SessionContext`` object's
existence (R9) -- plus REPL/clarification empty-input coverage (R10).
"""

import threading
from decimal import Decimal

import pytest
import requests

from agents.orchestrator import cli
from agents.orchestrator.agent import Result
from agents.orchestrator.brain import RuleBrain
from apps.marketplace.server.app import make_server as make_marketplace_server
from libs.p2p_client import P2PError
from registry.app import make_server as make_registry_server

# A local port nothing listens on: register() fails fast -> warning path.
DEAD_REGISTRY = "http://127.0.0.1:9"

MARKETPLACE_CAP = "marketplace.tasks"
TIMEOUT = 5.0


class FakeAgent(object):
    """Scripted stand-in for OrchestratorAgent (injection point of main)."""

    def __init__(self, results, register_ok=True):
        self.results = list(results)
        self.register_ok = register_ok
        self.register_calls = 0
        self.requests = []

    def register(self):
        self.register_calls += 1
        return self.register_ok

    def handle_request(self, nl_request, context=None):
        self.requests.append(nl_request)
        return self.results.pop(0)


class FakeTools(object):
    """Bounded fake U22 surface for driving the real agent stepwise path."""

    coordinator = None

    def __init__(self, candidates=None, cost="5"):
        self.candidates = (
            candidates
            if candidates is not None
            else [{"id": "marketplace", "kind": "app", "reputation": None}]
        )
        self.cost = cost

    def discover_candidates(self, capability):
        return list(self.candidates)

    def rank_candidates(self, candidates):
        return list(candidates)

    def request_terms(self, app_id, capability, input=None):  # noqa: A002
        return {
            "app_id": app_id,
            "capability": capability,
            "opportunities": [{"id": "task-1", "cost": self.cost}],
            "terms": [],
        }

    def report_to_user(self, message):
        return {"reported": True, "message": message}


def _real_agent_factory(args):
    """Real build_agent wiring, with the network rails swapped for fakes."""
    agent = cli.build_agent(args)
    agent.tools = FakeTools()
    return agent


def _no_input(prompt=""):
    raise EOFError()


# -- scenario 1: one-shot --request ----------------------------------------


def test_one_shot_prints_reply_and_exits_zero(capsys):
    agent = FakeAgent([Result(status="done", reply="Su paquete va en camino.")])
    rc = cli.main(
        [
            "--registry-url", DEAD_REGISTRY,
            "--request", "necesito enviar un paquete a Santiago",
        ],
        agent_factory=lambda args: agent,
        input_fn=_no_input,
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "Su paquete va en camino." in out
    assert agent.register_calls == 1
    assert agent.requests == ["necesito enviar un paquete a Santiago"]


def test_registry_unreachable_warns_but_continues(capsys):
    agent = FakeAgent(
        [Result(status="done", reply="Listo.")], register_ok=False
    )
    rc = cli.main(
        ["--registry-url", DEAD_REGISTRY, "--request", "hola tarea"],
        agent_factory=lambda args: agent,
        input_fn=_no_input,
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "warning" in out.lower()
    assert "Listo." in out


def test_declined_outcome_still_exits_zero(capsys):
    agent = FakeAgent([Result(status="declined", reply="No se aprobó.")])
    rc = cli.main(
        ["--registry-url", DEAD_REGISTRY, "--request", "algo"],
        agent_factory=lambda args: agent,
        input_fn=_no_input,
    )
    assert rc == 0
    assert "No se aprobó." in capsys.readouterr().out


# -- scenario 2: needs_clarification loop ----------------------------------


def test_clarification_reprompts_and_reinvokes_with_answer(capsys):
    agent = FakeAgent([
        Result(
            status="needs_clarification",
            reply="¿A qué destino desea enviar su paquete?",
        ),
        Result(status="done", reply="Enviado a Santiago."),
    ])
    answers = iter(["a Santiago"])
    rc = cli.main(
        [
            "--registry-url", DEAD_REGISTRY,
            "--request", "necesito enviar un paquete",
        ],
        agent_factory=lambda args: agent,
        input_fn=lambda prompt="": next(answers),
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "¿A qué destino desea enviar su paquete?" in out
    assert "Enviado a Santiago." in out
    # handle_request called twice; second call carries the answer.
    assert len(agent.requests) == 2
    assert "necesito enviar un paquete" in agent.requests[1]
    assert "a Santiago" in agent.requests[1]


def test_one_shot_clarification_without_stdin_prints_question_exit_zero(
    capsys,
):
    agent = FakeAgent([
        Result(status="needs_clarification", reply="¿A qué destino?"),
    ])
    rc = cli.main(
        ["--registry-url", DEAD_REGISTRY, "--request", "enviar paquete"],
        agent_factory=lambda args: agent,
        input_fn=_no_input,
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "¿A qué destino?" in out
    assert len(agent.requests) == 1  # no re-invocation without an answer


# -- scenario 3: approval prompt through the REAL wiring -------------------


@pytest.mark.parametrize(
    "answer,expected_status",
    [("y", "failed"), ("n", "declined")],
)
def test_approval_prompt_renders_and_reads_stdin(
    monkeypatch, capsys, answer, expected_status
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # cli_prompt_callback resolves builtins.input at call time.
    monkeypatch.setattr("builtins.input", lambda prompt="": answer)
    rc = cli.main(
        [
            "--registry-url", DEAD_REGISTRY,
            "--request", "necesito enviar un paquete a Santiago",
            "--auto-approve-under", "0",
            "--hard-ceiling", "20",
        ],
        agent_factory=_real_agent_factory,
    )
    out = capsys.readouterr().out
    assert rc == 0
    # The real cli_prompt_callback rendered action + cost.
    assert "Approval required for action: " in out
    assert "execute:shipping.package@marketplace" in out
    assert "Cost: 5" in out
    assert expected_status in out


# -- scenario 4: no API key -> RuleBrain notice, still functional ----------


def test_no_api_key_boots_rulebrain_with_notice(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rc = cli.main(
        [
            "--registry-url", DEAD_REGISTRY,
            "--request", "necesito enviar un paquete a Santiago",
            "--auto-approve-under", "10",  # cost 5 auto-approves: no prompt
        ],
        agent_factory=_real_agent_factory,
        input_fn=_no_input,
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "RuleBrain" in out
    assert "ANTHROPIC_API_KEY" in out
    # Approval is not execution: with no coordinator rail the orchestrator
    # must report the honest failed outcome, never fabricate "done".
    assert "failed" in out


def test_build_agent_uses_rulebrain_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    args = cli.build_parser().parse_args(["--registry-url", DEAD_REGISTRY])
    agent = cli.build_agent(args)
    assert isinstance(agent.brain, RuleBrain)
    assert agent.gate.policy.auto_approve_under == Decimal("0")
    assert agent.gate.policy.hard_ceiling == Decimal("20")
    assert agent.session is None


def test_require_signatures_builds_session(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    args = cli.build_parser().parse_args(
        ["--registry-url", DEAD_REGISTRY, "--require-signatures"]
    )
    agent = cli.build_agent(args)
    assert agent.session is not None
    assert agent.tools.session is agent.session
    # MVP convention: the session principal_id IS the base64 public key.
    assert agent.session.principal_id == agent.session.assertion.get(
        "principal_id", agent.session.principal_id
    )


def test_require_signatures_uses_one_effective_identity_everywhere(
    monkeypatch,
):
    """Regression (R1/P1): secure mode used to sign requests under the
    session's own principal_id while wiring ``--agent-id`` (a DIFFERENT,
    default value) into the gate/tools/agent -- every signed rail call
    then 403'd as an identity mismatch. All four must share ONE effective
    identity: the session's own principal_id, not the CLI default."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    args = cli.build_parser().parse_args([
        "--registry-url", DEAD_REGISTRY, "--require-signatures",
    ])
    agent = cli.build_agent(args)

    assert agent.session.principal_id != args.agent_id
    assert agent.session.principal_id == agent.tools.agent_principal_id
    assert agent.session.principal_id == agent.agent_id
    assert agent.gate.principal_id == agent.session.principal_id


# -- R9: real signature-enforcing marketplace stack -------------------------
#
# Mirrors tests/integration/test_secure_mode_end_to_end.py's ephemeral-port
# fixture pattern, scoped down to just Registry (unsigned public-key
# authority) + Marketplace (require_signatures=True) -- enough surface for
# request_terms's discover_work (P2P list.work_opportunities) round trip.


def _start(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def _url(server):
    host, port = server.server_address[:2]
    return "http://%s:%d" % (host, port)


def _identity_resolver(principal_id):
    """MVP resolver: a principal_id IS its own base64 public key."""
    return principal_id


def _register_agent(registry_url, principal_id, capabilities):
    resp = requests.post(
        "%s/agents/register" % registry_url,
        json={
            "principal_id": principal_id,
            "created_by": "user:cli-test-owner",
            "agent_card": {
                "name": "cli secure-mode test agent",
                "description": "U7 signed request_terms regression",
                "capabilities": capabilities,
            },
        },
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text


def _register_marketplace_app(registry_url, endpoint):
    resp = requests.post(
        "%s/apps/register" % registry_url,
        json={
            "app_id": "marketplace",
            "app_endpoint": endpoint,
            "p2p_endpoint": endpoint,
            "capabilities": [MARKETPLACE_CAP, "p2p.ping"],
        },
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text


def _create_task(marketplace_url, author, description):
    resp = requests.post(
        "%s/api/tasks" % marketplace_url,
        json={"principal_id": author, "description": description},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["task"]


class _SecureMarketplaceStack(object):
    def __init__(self, registry_url, marketplace_url):
        self.registry_url = registry_url
        self.marketplace_url = marketplace_url


@pytest.fixture
def secure_marketplace_stack():
    """Registry (unsigned) + Marketplace with ``require_signatures=True``,
    both on ephemeral ports, with the marketplace app pre-registered."""
    servers = []

    def spin(server):
        servers.append(server)
        _start(server)
        return _url(server)

    registry_url = spin(make_registry_server(port=0))
    marketplace_url = spin(make_marketplace_server(
        port=0, registry_url=registry_url, require_signatures=True,
        public_key_resolver=_identity_resolver,
    ))
    _register_marketplace_app(registry_url, marketplace_url)

    yield _SecureMarketplaceStack(registry_url, marketplace_url)

    for server in reversed(servers):
        server.shutdown()
        server.server_close()


def test_require_signatures_cli_wiring_signed_request_succeeds(
    monkeypatch, secure_marketplace_stack,
):
    """R9: ``--require-signatures`` against a REAL signature-enforcing
    marketplace actually lets a signed request_terms call succeed -- not
    merely build a SessionContext object."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    args = cli.build_parser().parse_args([
        "--registry-url", secure_marketplace_stack.registry_url,
        "--require-signatures",
    ])
    agent = cli.build_agent(args)
    # The agent's OWN effective identity (the session's public key) has to
    # be registered with the Registry to pass the target app's P2P
    # permission check.
    _register_agent(
        secure_marketplace_stack.registry_url, agent.agent_id,
        [MARKETPLACE_CAP],
    )
    task = _create_task(
        secure_marketplace_stack.marketplace_url, "user:author",
        "translate a doc",
    )

    result = agent.tools.request_terms("marketplace", MARKETPLACE_CAP)

    opportunity_ids = [o["id"] for o in result["opportunities"]]
    assert task["id"] in opportunity_ids


def test_require_signatures_cli_wiring_unsigned_request_rejected(
    monkeypatch, secure_marketplace_stack,
):
    """Control for the above (R9): the IDENTICAL registered principal,
    against the SAME signature-enforcing stack, but built WITHOUT
    --require-signatures, is rejected -- proving the passing test above
    actually discriminates signed vs. unsigned rather than merely not
    erroring for any input."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    signed_args = cli.build_parser().parse_args([
        "--registry-url", secure_marketplace_stack.registry_url,
        "--require-signatures",
    ])
    signed_agent = cli.build_agent(signed_args)
    _register_agent(
        secure_marketplace_stack.registry_url, signed_agent.agent_id,
        [MARKETPLACE_CAP],
    )

    # Same registered identity, same stack, but no --require-signatures:
    # build_agent leaves session=None so the coordinator signs nothing.
    unsigned_args = cli.build_parser().parse_args([
        "--registry-url", secure_marketplace_stack.registry_url,
        "--agent-id", signed_agent.agent_id,
    ])
    unsigned_agent = cli.build_agent(unsigned_args)
    assert unsigned_agent.session is None

    with pytest.raises(P2PError) as excinfo:
        unsigned_agent.tools.request_terms("marketplace", MARKETPLACE_CAP)
    assert "401" in str(excinfo.value)


# -- REPL (no --request) ---------------------------------------------------


def test_repl_handles_requests_until_eof(capsys):
    agent = FakeAgent([Result(status="done", reply="Hecho.")])
    lines = iter(["necesito enviar un paquete a Santiago"])

    def scripted(prompt=""):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError()

    rc = cli.main(
        ["--registry-url", DEAD_REGISTRY],
        agent_factory=lambda args: agent,
        input_fn=scripted,
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "Hecho." in out
    assert agent.requests == ["necesito enviar un paquete a Santiago"]


def test_repl_empty_line_does_not_exit_next_input_still_processed(capsys):
    """R10: a bare Enter at the REPL prompt is ``""`` (not EOF/quit) --
    the conversation keeps going and the next real line is still
    processed, instead of the REPL treating Enter as "salir"."""
    agent = FakeAgent([Result(status="done", reply="Hecho.")])
    lines = iter(["", "necesito enviar un paquete a Santiago"])

    def scripted(prompt=""):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError()

    rc = cli.main(
        ["--registry-url", DEAD_REGISTRY],
        agent_factory=lambda args: agent,
        input_fn=scripted,
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "Hecho." in out
    # Only ONE handle_request call, carrying the real (non-empty) line --
    # the empty line never became a request nor ended the REPL.
    assert agent.requests == ["necesito enviar un paquete a Santiago"]


def test_mid_clarification_empty_answer_reasks_question(capsys):
    """R10: an empty answer to a clarifying question re-asks it (loops
    back with the SAME request) instead of being treated as "no answer
    available", which would otherwise end the one-shot conversation right
    there with the question still standing as the final outcome."""
    agent = FakeAgent([
        Result(
            status="needs_clarification",
            reply="¿A qué destino desea enviar su paquete?",
        ),
        Result(
            status="needs_clarification",
            reply="¿A qué destino desea enviar su paquete?",
        ),
        Result(status="done", reply="Enviado a Santiago."),
    ])
    answers = iter(["", "a Santiago"])
    rc = cli.main(
        [
            "--registry-url", DEAD_REGISTRY,
            "--request", "necesito enviar un paquete",
        ],
        agent_factory=lambda args: agent,
        input_fn=lambda prompt="": next(answers),
    )
    out = capsys.readouterr().out
    assert rc == 0
    # The clarifying question was printed TWICE: once, then re-asked after
    # the empty answer.
    assert out.count("¿A qué destino desea enviar su paquete?") == 2
    assert "Enviado a Santiago." in out
    # Three handle_request calls: initial, re-ask (same request, empty
    # answer never appended), then the real answer appended.
    assert len(agent.requests) == 3
    assert agent.requests[0] == "necesito enviar un paquete"
    assert agent.requests[1] == "necesito enviar un paquete"
    assert "a Santiago" in agent.requests[2]


# -- supplement: argparse behavior -----------------------------------------


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])
    assert excinfo.value.code == 0
    assert "--registry-url" in capsys.readouterr().out


def test_bad_decimal_hard_ceiling_errors_nonzero(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(
            [
                "--registry-url", DEAD_REGISTRY,
                "--hard-ceiling", "not-a-number",
                "--request", "hola",
            ]
        )
    assert excinfo.value.code != 0
    assert "hard-ceiling" in capsys.readouterr().err


def test_ceiling_below_floor_is_clear_error(capsys):
    rc = cli.main(
        [
            "--registry-url", DEAD_REGISTRY,
            "--auto-approve-under", "10",
            "--hard-ceiling", "5",
            "--request", "hola",
        ],
        input_fn=_no_input,
    )
    captured = capsys.readouterr()
    assert rc != 0
    assert "hard_ceiling" in (captured.err + captured.out)
