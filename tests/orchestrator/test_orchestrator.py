"""Tests for the orchestrator concierge agent (unit U24).

Covers the plan's seven scenarios:

1. Happy path (RuleBrain + faithful tool stubs): matching app is
   discovered, terms requested, the $0 cost auto-approved by the gate,
   the work executed over the coordinator rail, ``status == "done"``.
2. Ambiguous request -> ``needs_clarification`` with a question and NO
   discovery/spend attempted (spies stay empty).
3. No candidate -> ``no_candidate``, polite reply, no spend.
4. Gate denies a paid action (auto_deny + gray-zone cost) ->
   ``declined``; the app is NOT executed; the reply explains why.
5. Cost over the hard ceiling with an always-approve callback -> still
   ``declined``; the reply names the ceiling.
6. ``register()`` is idempotent against a real ephemeral Registry.
7. ClaudeBrain path with an injected fake client/tool-runner completes a
   scripted tool sequence (LLM-driven wiring, no network).

U6 adds nine more scenarios covering the tool-runner path's
``execute_work`` wiring, honest status derivation and cumulative-spend
cap (KTD2/KTD7) -- see ``TestClaudeBrainPath``/``TestToolRunnerExecuteWork``
below.
"""

import json
import threading
from decimal import Decimal
from types import SimpleNamespace

import pytest

from agents.orchestrator.agent import OrchestratorAgent, Result
from agents.orchestrator.approval import (
    ApprovalGate,
    SpendPolicy,
    always_approve_callback,
    auto_deny_callback,
)
from agents.orchestrator.brain import ClaudeBrain, Intent, RuleBrain
from agents.orchestrator.tools import OrchestratorTools, OutcomeTracker
from registry.app import make_server as make_registry_server

SHIPPING_CAP = "shipping.package"


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _NullAudit(object):
    def log(self, *args, **kwargs):
        pass


class RecordingGate(object):
    """Real U23 gate semantics + a record of every require() call."""

    def __init__(self, policy, callback):
        self._gate = ApprovalGate(policy, callback, audit_client=_NullAudit())
        self.calls = []
        # Exposed so agent.py can floor an unparseable cost at the
        # policy's auto_approve_under (mirrors real ApprovalGate.policy).
        self.policy = policy

    def require(self, action, cost, details=None):
        self.calls.append((action, cost))
        return self._gate.require(action, cost, details)


def make_gate(callback=auto_deny_callback, under="1", ceiling="100"):
    return RecordingGate(
        SpendPolicy(
            auto_approve_under=Decimal(under), hard_ceiling=Decimal(ceiling)
        ),
        callback,
    )


class SpyCoordinator(object):
    """AgentCoordinator double recording submitted bids."""

    def __init__(self):
        self.bids = []

    def submit_bid(self, app_id, task_id, proposed_terms,
                   agent_reputation_note=None):
        self.bids.append((app_id, task_id, proposed_terms))
        return {"id": "bid-1", "task_id": task_id, "status": "pending"}


class SpyTools(object):
    """Faithful stub of the OrchestratorTools surface, recording calls."""

    def __init__(self, candidates=None, terms=None, credential=None):
        self.calls = []
        self.reported = []
        self.candidates = candidates if candidates is not None else []
        self.terms = terms if terms is not None else {
            "opportunities": [], "terms": [],
        }
        self.credential = credential or {"granted": True, "reason": "ok"}
        self.coordinator = SpyCoordinator()

    def discover_candidates(self, capability):
        self.calls.append(("discover_candidates", capability))
        return list(self.candidates)

    def rank_candidates(self, candidates):
        self.calls.append(("rank_candidates", list(candidates)))
        return list(candidates)

    def request_terms(self, app_id, capability, input=None):  # noqa: A002
        self.calls.append(("request_terms", app_id, capability, input))
        result = dict(self.terms)
        result.setdefault("app_id", app_id)
        result.setdefault("capability", capability)
        return result

    def request_credential_access(self, credential_id, cost=None,
                                  details=None):
        self.calls.append(("request_credential_access", credential_id))
        return dict(self.credential)

    def report_to_user(self, message):
        self.reported.append(message)
        return {"reported": True, "message": message}


class CandidateTermsTools(SpyTools):
    """Spy whose terms vary by candidate, for shortlist comparison tests."""

    def __init__(self, candidates, terms_by_candidate):
        super().__init__(candidates=candidates)
        self.terms_by_candidate = terms_by_candidate

    def request_terms(self, app_id, capability, input=None):  # noqa: A002
        self.calls.append(("request_terms", app_id, capability, input))
        result = dict(self.terms_by_candidate[app_id])
        result.setdefault("app_id", app_id)
        result.setdefault("capability", capability)
        return result


class IntentBrain(object):
    def __init__(self, intent):
        self.intent = intent
        self.replies = RuleBrain()

    def understand(self, nl_request, context=None):
        return self.intent

    def compose_reply(self, state):
        return self.replies.compose_reply(state)


def shipping_candidates():
    return [{"id": "shipping", "kind": "app", "reputation": None}]


def open_terms(terms=None, opportunities=None):
    return {
        "opportunities": (
            opportunities if opportunities is not None
            else [{"id": "task-1", "description": "enviar paquete"}]
        ),
        "terms": terms or [],
    }


def make_agent(tools, gate, brain=None, registry_url="http://registry.invalid"):
    return OrchestratorAgent(
        registry_url=registry_url,
        brain=brain or RuleBrain(),
        tools=tools,
        gate=gate,
    )


# ---------------------------------------------------------------------------
# U6 test doubles: a REAL OrchestratorTools wired to lightweight federation
# /coordinator stand-ins, so the tool-runner-path tests below drive the
# ACTUAL U22/U5 tool implementations (discover_candidates, execute_work's
# self-grounded re-discovery, the real ApprovalGate/SpendPolicy semantics)
# through a scripted-but-real fake tool runner -- not just a scripted final
# message (the execution note's residual-risk closure).
# ---------------------------------------------------------------------------


class StubFederation(object):
    """``FederationClient`` double: apps registered per capability."""

    def __init__(self, apps_by_capability):
        self.apps_by_capability = apps_by_capability

    def discover_apps(self, capability=None):
        return list(self.apps_by_capability.get(capability, []))


class StubCoordinator(object):
    """``AgentCoordinator`` double for the tool-runner ``execute_work``
    tests: records every ``discover_work``/``submit_bid`` call, optionally
    raising to simulate a rail failure."""

    def __init__(self, opportunities=None, raise_on_discover=None,
                 raise_on_submit=None):
        self.discover_calls = []
        self.bids = []
        self._opportunities = (
            [{"id": "task-1"}] if opportunities is None else opportunities
        )
        self._raise_on_discover = raise_on_discover
        self._raise_on_submit = raise_on_submit

    def discover_work(self, app_id, capability_id=None):
        self.discover_calls.append((app_id, capability_id))
        if self._raise_on_discover is not None:
            raise self._raise_on_discover
        return list(self._opportunities)

    def submit_bid(self, app_id, task_id, proposed_terms,
                   agent_reputation_note=None):
        if self._raise_on_submit is not None:
            raise self._raise_on_submit
        self.bids.append((app_id, task_id, proposed_terms))
        return {"id": "bid-1", "task_id": task_id, "status": "pending"}

    def check_bid_status(self, app_id, task_id):
        return {"task": {"status": "open", "bids": []}}


def make_real_tools(gate, coordinator=None, federation=None, reporter=None):
    """A real :class:`OrchestratorTools` wired to the stubs above -- the
    SAME shared U22/U5 implementations the tool-runner path (and
    ``_handle_stepwise``) use, just with a lightweight federation/
    coordinator instead of a live HTTP rail."""
    return OrchestratorTools(
        federation_client=(
            federation if federation is not None
            else StubFederation({SHIPPING_CAP: [{"app_id": "shipping"}]})
        ),
        coordinator=coordinator if coordinator is not None else StubCoordinator(),
        gate=gate,
        agent_principal_id="agent:orchestrator",
        reporter=reporter,
    )


# ---------------------------------------------------------------------------
# 1. Happy path (RuleBrain, stubbed tools)
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_full_flow_ends_done_with_reply(self):
        # An EXPLICIT, parseable zero-cost term (U2/R5 scenario 2): the
        # genuinely-free case must still auto-approve silently and is
        # unaffected by the "nothing parseable" fallback floor below.
        tools = SpyTools(
            candidates=shipping_candidates(),
            terms=open_terms(terms=[{
                "agent": "agent:worker",
                "terms": "0 credits, ready today",
                "status": "pending",
            }]),
        )
        gate = make_gate()  # $0 cost < auto_approve_under(1): silent approval
        agent = make_agent(tools, gate)

        result = agent.handle_request("Necesito enviar un paquete a Santiago")

        assert isinstance(result, Result)
        assert result.status == "done"
        assert result.reply  # non-empty, courteous reply
        # The fixed tool sequence ran: discover -> rank -> terms.
        assert [call[0] for call in tools.calls] == [
            "discover_candidates", "rank_candidates", "request_terms",
        ]
        assert tools.calls[0] == ("discover_candidates", SHIPPING_CAP)
        # The spend was gated (even at $0) and derived from the terms.
        assert gate.calls == [
            ("execute:%s@shipping" % SHIPPING_CAP, Decimal("0")),
        ]
        # The work was executed over the coordinator rail: one bid on the
        # top open opportunity of the chosen app.
        assert len(tools.coordinator.bids) == 1
        assert tools.coordinator.bids[0][:2] == ("shipping", "task-1")
        # The reply was surfaced through the tools' reporter hook too.
        assert result.reply in tools.reported
        assert result.evidence["execution"]["executed"] is True


# ---------------------------------------------------------------------------
# 2. Ambiguous request -> clarification, NO discovery/spend
# ---------------------------------------------------------------------------


class TestNeedsClarification:
    def test_ambiguous_request_asks_a_question_and_touches_nothing(self):
        tools = SpyTools(candidates=shipping_candidates(), terms=open_terms())
        gate = make_gate()
        agent = make_agent(tools, gate)

        result = agent.handle_request("hola, buenas tardes")

        assert result.status == "needs_clarification"
        assert "?" in result.reply  # a courteous question came back
        # NO discovery, NO spend, NO execution was attempted.
        assert tools.calls == []
        assert gate.calls == []
        assert tools.coordinator.bids == []

    def test_known_capability_with_missing_param_also_clarifies(self):
        tools = SpyTools(candidates=shipping_candidates(), terms=open_terms())
        gate = make_gate()
        agent = make_agent(tools, gate)

        # Shipping intent without a destination -> RuleBrain flags it.
        result = agent.handle_request("necesito enviar un paquete")

        assert result.status == "needs_clarification"
        assert result.reply
        assert tools.calls == []
        assert gate.calls == []

    def test_explicit_not_ready_never_searches_even_without_a_question(self):
        tools = SpyTools(candidates=shipping_candidates(), terms=open_terms())
        intent = Intent(
            capability=SHIPPING_CAP,
            ready_to_search=False,
            confidence=0.4,
        )
        agent = make_agent(tools, make_gate(), brain=IntentBrain(intent))

        result = agent.handle_request("todavía no estoy seguro")

        assert result.status == "needs_clarification"
        assert "?" in result.reply
        assert tools.calls == []

    def test_social_turn_is_answered_without_replaying_work(self):
        tools = SpyTools(candidates=shipping_candidates(), terms=open_terms())
        intent = Intent(
            capability=SHIPPING_CAP,
            conversation_act="social",
            ready_to_search=False,
            user_message="Con gusto. Aquí estoy cuando me necesites.",
        )
        agent = make_agent(tools, make_gate(), brain=IntentBrain(intent))

        result = agent.handle_request("gracias")

        assert result.status == "conversation"
        assert "Con gusto" in result.reply
        assert tools.calls == []
        assert tools.coordinator.bids == []

    def test_memory_question_is_conversation_not_clarification(self):
        tools = SpyTools(candidates=shipping_candidates())
        agent = make_agent(tools, make_gate(), brain=RuleBrain())
        context = {
            "conversation": [
                {
                    "role": "user",
                    "text": "Necesito saber de qué estábamos hablando",
                },
                {
                    "role": "concierge",
                    "text": "¿Podrías proporcionar más detalles?",
                },
            ]
        }

        result = agent.handle_request(
            "¿De qué hablábamos en la otra conversación?",
            context=context,
        )

        assert result.status == "conversation"
        assert "No puedo ver otras conversaciones" in result.reply
        assert tools.calls == []


# ---------------------------------------------------------------------------
# 3. No candidate -> polite explanation, no spend
# ---------------------------------------------------------------------------


class TestNoCandidate:
    def test_empty_discovery_ends_politely_with_no_spend(self):
        tools = SpyTools(candidates=[])
        gate = make_gate()
        agent = make_agent(tools, gate)

        result = agent.handle_request("Necesito enviar un paquete a Santiago")

        assert result.status == "no_candidate"
        assert result.reply == (
            "No encontré un agente disponible. No se realizó ningún cargo."
        )
        # Discovery happened, then the flow stopped: no terms, no gate,
        # no execution.
        assert [call[0] for call in tools.calls] == ["discover_candidates"]
        assert gate.calls == []
        assert tools.coordinator.bids == []


class TestCandidateInvestigation:
    def test_skips_unengageable_agent_and_uses_viable_app(self):
        candidates = [
            {"id": "agent-only", "kind": "agent", "reputation": {
                "verification_rate": 1.0, "tasks_verified": 100,
            }},
            {"id": "shipping-app", "kind": "app", "reputation": {
                "verification_rate": 0.95, "tasks_verified": 20,
            }},
        ]
        tools = CandidateTermsTools(
            candidates,
            {"shipping-app": open_terms(terms=[{
                "terms": "0 credits", "status": "pending",
            }])},
        )
        agent = make_agent(tools, make_gate())

        result = agent.handle_request("Enviar paquete a Santiago")

        assert result.status == "done"
        assert result.evidence["candidate"]["id"] == "shipping-app"
        assert not any(
            call[0] == "request_terms" and call[1] == "agent-only"
            for call in tools.calls
        )

    def test_lowest_cost_preference_compares_shortlist_terms(self):
        candidates = [
            {"id": "premium", "kind": "app", "reputation": {
                "verification_rate": 1.0, "tasks_verified": 20,
            }},
            {"id": "value", "kind": "app", "reputation": {
                "verification_rate": 0.95, "tasks_verified": 15,
            }},
        ]
        tools = CandidateTermsTools(
            candidates,
            {
                "premium": open_terms(
                    terms=[{"terms": "10 credits", "status": "pending"}],
                    opportunities=[{"id": "task-premium"}],
                ),
                "value": open_terms(
                    terms=[{"terms": "3 credits", "status": "pending"}],
                    opportunities=[{"id": "task-value"}],
                ),
            },
        )
        gate = make_gate(callback=always_approve_callback)
        brain = IntentBrain(Intent(
            capability=SHIPPING_CAP,
            params={"destination": "Santiago"},
            preferences={"priority": "lowest_cost"},
            ready_to_search=True,
            confidence=0.98,
        ))
        agent = make_agent(tools, gate, brain=brain)

        result = agent.handle_request("Busca la opción más barata")

        assert result.status == "done"
        assert result.evidence["candidate"]["id"] == "value"
        assert result.evidence["cost"] == "3"
        assert [call[1] for call in tools.calls
                if call[0] == "request_terms"] == ["premium", "value"]
        assert tools.coordinator.bids[0][:2] == ("value", "task-value")


# ---------------------------------------------------------------------------
# 4. Gate denies a paid action (gray zone + auto_deny)
# ---------------------------------------------------------------------------


class TestGateDenies:
    def test_gray_zone_denial_declines_without_executing(self):
        # (Also U2/R5 scenario 3 regression guard: a real, parseable cost
        # above the floor reaches the gate unchanged.)
        # Terms carry a real cost (5), inside the gray zone [1, 100].
        tools = SpyTools(
            candidates=shipping_candidates(),
            terms=open_terms(terms=[{
                "agent": "agent:worker",
                "terms": "5 credits, done today",
                "status": "pending",
            }]),
        )
        gate = make_gate(callback=auto_deny_callback)
        agent = make_agent(tools, gate)

        result = agent.handle_request("Necesito enviar un paquete a Santiago")

        assert result.status == "declined"
        # The gate saw the derived Decimal cost for the execute action.
        assert gate.calls == [
            ("execute:%s@shipping" % SHIPPING_CAP, Decimal("5")),
        ]
        # The app was NOT executed.
        assert tools.coordinator.bids == []
        # The reply explains why (the gate's reason is surfaced).
        assert "denied by approval callback" in result.reply
        assert result.evidence["decision"]["approved"] is False


# ---------------------------------------------------------------------------
# U22/R6: a denied credential must stop _handle_stepwise before execution,
# even after the execute-cost gate itself approved.
# ---------------------------------------------------------------------------


class TestCredentialGatedFlow:
    def test_credential_denial_stops_execution_after_the_cost_gate_approves(
        self,
    ):
        tools = SpyTools(
            candidates=shipping_candidates(),
            terms=open_terms(terms=[{
                "agent": "agent:worker",
                "terms": "0 credits, ready today",
                "status": "pending",
            }]),
            credential={
                "granted": False, "reason": "vault denied access",
            },
        )
        gate = make_gate()  # $0 cost < auto_approve_under(1): silent approval
        agent = OrchestratorAgent(
            registry_url="http://registry.invalid",
            brain=RuleBrain(),
            tools=tools,
            gate=gate,
            credential_id="cred-1",
        )

        result = agent.handle_request("Necesito enviar un paquete a Santiago")

        assert result.status == "failed"
        assert "no fue autorizado" in result.reply
        assert result.evidence["credential"] == {
            "credential_id": "cred-1", "granted": False,
        }
        # The execute-cost gate DID approve (the credential step is
        # separate and comes after) but _execute must never run.
        assert gate.calls == [
            ("execute:%s@shipping" % SHIPPING_CAP, Decimal("0")),
        ]
        assert tools.coordinator.bids == []


# ---------------------------------------------------------------------------
# U2 (R5/KTD4): unparseable/absent cost must never silently auto-approve
# ---------------------------------------------------------------------------


class TestUnparseableCostFloor:
    """``derive_cost`` must distinguish "found an explicit zero" from
    "found nothing parseable anywhere in the terms"; the latter must be
    floored at ``auto_approve_under`` so the gate's callback is always
    consulted, never silently approved (scenario 1)."""

    def test_no_cost_bearing_field_anywhere_consults_the_callback(self):
        consulted = []

        def spy_callback(action, cost, details=None):
            consulted.append((action, cost))
            return True  # approve once consulted, proving it WAS asked

        # Neither the bid "terms" strings nor the opportunity carry any
        # cost/price/budget/amount field anywhere -- nothing parseable.
        tools = SpyTools(
            candidates=shipping_candidates(),
            terms=open_terms(
                terms=[],
                opportunities=[
                    {"id": "task-1", "description": "enviar paquete"},
                ],
            ),
        )
        gate = make_gate(callback=spy_callback, under="1", ceiling="100")
        agent = make_agent(tools, gate)

        result = agent.handle_request("Necesito enviar un paquete a Santiago")

        # The callback WAS consulted -- never silently approved -- at a
        # cost floored to (at least) the auto-approve threshold.
        assert len(consulted) == 1
        assert consulted[0][1] >= Decimal("1")
        assert gate.calls == [
            ("execute:%s@shipping" % SHIPPING_CAP, Decimal("1")),
        ]
        assert result.status == "done"  # the spy callback approved it

    def test_no_cost_bearing_field_anywhere_is_declined_by_auto_deny(self):
        # Same unparseable terms, but with the locked-down/unattended
        # callback: proves the floored cost lands in the gray zone and is
        # NOT silently approved -- the old bug auto-approved this at $0.
        tools = SpyTools(
            candidates=shipping_candidates(),
            terms=open_terms(terms=[], opportunities=[]),
        )
        gate = make_gate(callback=auto_deny_callback, under="1", ceiling="100")
        agent = make_agent(tools, gate)

        result = agent.handle_request("Necesito enviar un paquete a Santiago")

        assert gate.calls == [
            ("execute:%s@shipping" % SHIPPING_CAP, Decimal("1")),
        ]
        assert result.status == "declined"
        assert tools.coordinator.bids == []


# ---------------------------------------------------------------------------
# 5. Over the hard ceiling: even always-approve cannot override
# ---------------------------------------------------------------------------


class TestHardCeiling:
    def test_over_ceiling_declined_and_reply_names_the_ceiling(self):
        tools = SpyTools(
            candidates=shipping_candidates(),
            terms=open_terms(terms=[{
                "agent": "agent:worker",
                "terms": "500 credits up front",
                "status": "pending",
            }]),
        )
        gate = make_gate(callback=always_approve_callback, ceiling="100")
        agent = make_agent(tools, gate)

        result = agent.handle_request("Necesito enviar un paquete a Santiago")

        assert result.status == "declined"
        assert tools.coordinator.bids == []  # never executed
        # The ceiling is named in the user-facing reply.
        assert "hard ceiling" in result.reply
        assert "100" in result.reply
        assert "500" in result.reply


# ---------------------------------------------------------------------------
# 6. register() is idempotent (real ephemeral Registry)
# ---------------------------------------------------------------------------


def _start(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


@pytest.fixture
def registry():
    server = make_registry_server(port=0)
    _start(server)
    host, port = server.server_address[:2]
    yield "http://%s:%d" % (host, port)
    server.shutdown()
    server.server_close()


class TestRegister:
    def test_register_twice_is_success_both_times(self, registry):
        agent = make_agent(
            SpyTools(), make_gate(), registry_url=registry
        )
        assert agent.register() is True
        # Second registration of the SAME principal: the Registry answers
        # 409, which the agent treats as success (idempotent).
        assert agent.register() is True

    def test_unreachable_registry_is_false_not_an_exception(self):
        agent = make_agent(
            SpyTools(), make_gate(),
            registry_url="http://127.0.0.1:1",  # nothing listens here
        )
        assert agent.register() is False


# ---------------------------------------------------------------------------
# 7. ClaudeBrain path: injected fake client drives a scripted tool loop
# ---------------------------------------------------------------------------


class FakeToolRunner(object):
    """Scripted stand-in for ``client.beta.messages.tool_runner(...)``.

    Iterating it executes the scripted tool calls against the REAL
    ``@beta_tool`` wrappers it was handed (proving the agent wired the
    shared U22+U5 implementations into the runner), then yields a final
    text message -- unless ``final_text`` is ``None``, in which case NO
    final text is ever yielded (U6 scenario 4: simulates ``max_iterations``
    being exhausted mid-conversation, with nothing synthesized at the
    end).
    """

    def __init__(self, tools, script, final_text):
        self.tools_by_name = {tool.name: tool for tool in tools}
        self.script = script
        self.final_text = final_text
        self.tool_outputs = []

    def __iter__(self):
        for name, kwargs in self.script:
            output = self.tools_by_name[name].func(**kwargs)
            self.tool_outputs.append((name, output))
            yield SimpleNamespace(
                content=[SimpleNamespace(type="tool_use", name=name)],
                stop_reason="tool_use",
            )
        if self.final_text is not None:
            yield SimpleNamespace(
                content=[SimpleNamespace(type="text", text=self.final_text)],
                stop_reason="end_turn",
            )


class FakeClaudeClient(object):
    """Anthropic client double: messages.parse + beta tool runner."""

    def __init__(self, intent, script, final_text):
        self._intent = intent
        self._script = script
        self._final_text = final_text
        self.runner_kwargs = None
        self.runner = None
        self.messages = SimpleNamespace(
            parse=self._parse, create=self._create
        )
        self.beta = SimpleNamespace(
            messages=SimpleNamespace(tool_runner=self._tool_runner)
        )

    def _parse(self, **kwargs):
        return SimpleNamespace(parsed_output=self._intent)

    def _create(self, **kwargs):
        # Echoes the state it was asked to compose a reply for (instead
        # of a fixed string) so tests can assert the FALLBACK reply
        # (used when the tool loop itself produced no final text)
        # reflects the honestly-derived status/outcome, e.g. a decline
        # reason -- exactly like RuleBrain.compose_reply does for the
        # deterministic path.
        content = kwargs.get("messages", [{}])[-1].get("content", "")
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="(fallback) %s" % content)]
        )

    def _tool_runner(self, **kwargs):
        self.runner_kwargs = kwargs
        self.runner = FakeToolRunner(
            kwargs["tools"], self._script, self._final_text
        )
        return self.runner


class TestClaudeBrainPath:
    # -- U6 scenario 1: discover -> rank -> terms -> execute_work (approved)
    #    -> "done", driven through the REAL U22/U5 tool implementations. --

    def test_scripted_tool_sequence_completes_without_network(self):
        intent = Intent(
            capability=SHIPPING_CAP,
            params={"destination": "Santiago"},
            user_message="Con gusto.",
        )
        reported = []
        coordinator = StubCoordinator(opportunities=[{"id": "task-1"}])
        # always_approve: the wrapper always floors the model-claimed cost
        # to at least auto_approve_under (R6, never silently below it),
        # so every LLM-path execute_work call lands in the gray zone and
        # needs the callback -- proven approved here.
        gate = make_gate(callback=always_approve_callback)
        tools = make_real_tools(
            gate, coordinator=coordinator, reporter=reported.append,
        )
        script = [
            ("discover_candidates", {"capability": SHIPPING_CAP}),
            ("rank_candidates", {"candidates": shipping_candidates()}),
            ("request_terms",
             {"app_id": "shipping", "capability": SHIPPING_CAP}),
            ("report_to_user",
             {"message": "Encontré un servicio de envíos."}),
            ("execute_work",
             {"app_id": "shipping", "capability": SHIPPING_CAP,
              "cost": "0"}),
        ]
        final_text = "Listo, su paquete será enviado a Santiago."
        client = FakeClaudeClient(intent, script, final_text)
        agent = make_agent(
            tools, gate, brain=ClaudeBrain(client=client)
        )

        result = agent.handle_request("Necesito enviar un paquete a Santiago")

        assert result.status == "done"
        assert result.reply == final_text
        assert result.evidence["path"] == "tool_runner"
        # The tool-runner path's evidence carries the same
        # candidate/cost signal the deterministic path's evidence does
        # (agent-native parity) -- not just the bare outcome string.
        assert result.evidence["execution"]["candidate"] == "shipping"
        assert result.evidence["execution"]["cost"] == "1"
        # The runner got EXACTLY the bounded U22+U5 tool surface (U6 folds
        # execute_work in), and a bounded iteration budget.
        names = {tool.name for tool in client.runner_kwargs["tools"]}
        assert names == {
            "discover_candidates",
            "rank_candidates",
            "request_terms",
            "request_credential_access",
            "report_to_user",
            "execute_work",
        }
        assert client.runner_kwargs["max_iterations"] == agent.max_iterations
        # The scripted tool calls hit the SHARED, REAL implementations.
        assert reported == ["Encontré un servicio de envíos."]
        # execute_work really submitted a signed bid via the shared
        # submit_work_bid helper (U5/KTD6) -- not a mock.
        assert coordinator.bids == [(
            "shipping", "task-1",
            "handled by agent:orchestrator on behalf of the user",
        )]
        # Every scripted tool call produced JSON output for the loop.
        assert len(client.runner.tool_outputs) == len(script)

    def test_claude_brain_still_clarifies_before_any_tool_runs(self):
        intent = Intent(
            capability="",
            missing_info=["¿Qué desea enviar y hacia dónde?"],
            user_message="Con gusto le ayudo.",
        )
        client = FakeClaudeClient(intent, script=[], final_text="unused")
        tools = SpyTools(candidates=shipping_candidates())
        agent = make_agent(
            tools, make_gate(), brain=ClaudeBrain(client=client)
        )

        result = agent.handle_request("hola")

        assert result.status == "needs_clarification"
        assert "¿Qué desea enviar y hacia dónde?" in result.reply
        # The tool runner was never even built.
        assert client.runner_kwargs is None
        assert tools.calls == []


# ---------------------------------------------------------------------------
# U6: execute_work wired into the tool-runner path -- honest status,
# cumulative-spend cap, precedence, per-request tracker isolation.
# ---------------------------------------------------------------------------


def _shipping_intent():
    return Intent(
        capability=SHIPPING_CAP,
        params={"destination": "Santiago"},
        user_message="Con gusto.",
    )


class TestOutcomeTrackerDistinguishesExecutedFromDiscussed:
    """Execution-note-mandated first failing test: the tracker must tell
    "executed" apart from "discussed but never executed" BEFORE any
    tool-runner wiring is exercised -- exercised directly against the raw
    :class:`OrchestratorTools` methods."""

    def test_declined_then_reset_never_reports_executed(self):
        gate = make_gate(callback=auto_deny_callback, under="1", ceiling="100")
        tools = make_real_tools(gate)
        tools._outcome = OutcomeTracker()

        result = tools.request_credential_access("cred-1", cost=Decimal("5"))

        assert result["granted"] is False
        # Discussed (a gate denial was recorded) but nothing was ever
        # executed -- the tracker must say so, not "done".
        assert tools._outcome.declined is True
        assert tools._outcome.executed is False
        assert tools._outcome.status() == "declined"

    def test_real_execution_reports_done_even_after_an_earlier_decline(self):
        gate = make_gate(callback=auto_deny_callback, under="1", ceiling="100")
        coordinator = StubCoordinator(opportunities=[{"id": "task-1"}])
        tools = make_real_tools(gate, coordinator=coordinator)
        tools._outcome = OutcomeTracker()

        tools.request_credential_access("cred-1", cost=Decimal("5"))  # denied
        # A DIFFERENT action (execute:...) approved by a permissive gate:
        tools.gate = ApprovalGate(
            SpendPolicy(auto_approve_under=Decimal("1"),
                        hard_ceiling=Decimal("100")),
            always_approve_callback, audit_client=_NullAudit(),
        )
        executed = tools.execute_work(
            "shipping", SHIPPING_CAP, Decimal("1")
        )

        assert executed["executed"] is True
        assert tools._outcome.executed is True
        # KTD2 precedence: done wins even though a decline was recorded
        # earlier in the SAME tracker.
        assert tools._outcome.status() == "done"

    def test_concurrent_requests_have_isolated_outcome_trackers(self):
        tools = make_real_tools(make_gate())
        barrier = threading.Barrier(2)
        observed = {}

        def run(name, amount):
            tools._outcome = OutcomeTracker()
            tools._outcome.running_cost = Decimal(amount)
            barrier.wait()
            observed[name] = tools._outcome.running_cost

        first = threading.Thread(target=run, args=("first", "3"))
        second = threading.Thread(target=run, args=("second", "9"))
        first.start()
        second.start()
        first.join()
        second.join()

        assert observed == {
            "first": Decimal("3"),
            "second": Decimal("9"),
        }


class TestCumulativeSpendCeiling:
    """Execution-note-mandated second failing test: cumulative spend
    across multiple calls sharing ONE tracker must be checked against
    ``hard_ceiling``, not each call's own cost in isolation (R12/KTD7) --
    exercised directly at the ``OrchestratorTools`` level first."""

    def test_second_call_is_refused_on_the_running_total(self):
        # Each call ALONE is comfortably within auto_approve_under (10)
        # and would silently auto-approve on its own; their SUM (16)
        # exceeds hard_ceiling (15).
        gate = ApprovalGate(
            SpendPolicy(auto_approve_under=Decimal("10"),
                        hard_ceiling=Decimal("15")),
            always_approve_callback, audit_client=_NullAudit(),
        )
        coordinator = StubCoordinator(opportunities=[{"id": "task-1"}])
        tools = make_real_tools(gate, coordinator=coordinator)
        tools._outcome = OutcomeTracker()

        first = tools.execute_work("shipping", SHIPPING_CAP, Decimal("8"))
        second = tools.execute_work("shipping", SHIPPING_CAP, Decimal("8"))

        assert first["executed"] is True
        assert second["executed"] is False
        assert "hard ceiling" in second["reason"]
        # Only the FIRST call actually bid -- the second was refused
        # before ever reaching the coordinator's submit_bid.
        assert len(coordinator.bids) == 1
        assert tools._outcome.running_cost == Decimal("8")
        # Precedence still resolves to done: something real DID execute.
        assert tools._outcome.status() == "done"

    def test_credential_access_and_execute_work_share_one_running_total(
        self,
    ):
        """The cumulative ceiling (R12/KTD7) must hold ACROSS the two
        different gated tools, not just within repeated calls to the
        same one -- an approved credential_access cost must count
        against a later execute_work call sharing the same tracker."""

        class _StubVault(object):
            def request_access(self, credential_id, agent_principal_id):
                return {"access_granted": True}

        # Each call ALONE is within auto_approve_under (10); their SUM
        # (8 + 8 = 16) exceeds hard_ceiling (15).
        gate = ApprovalGate(
            SpendPolicy(auto_approve_under=Decimal("10"),
                        hard_ceiling=Decimal("15")),
            always_approve_callback, audit_client=_NullAudit(),
        )
        coordinator = StubCoordinator(opportunities=[{"id": "task-1"}])
        tools = make_real_tools(gate, coordinator=coordinator)
        tools.vault = _StubVault()
        tools._outcome = OutcomeTracker()

        credential = tools.request_credential_access(
            "cred-1", cost=Decimal("8")
        )
        execution = tools.execute_work(
            "shipping", SHIPPING_CAP, Decimal("8")
        )

        assert credential["granted"] is True
        assert execution["executed"] is False
        assert "hard ceiling" in execution["reason"]
        # The refused execute_work never reached the coordinator.
        assert coordinator.bids == []
        # running_cost reflects ONLY the approved credential cost.
        assert tools._outcome.running_cost == Decimal("8")


class TestToolRunnerExecuteWork:
    """U6 scenarios 2-7: execute_work through the tool-runner path,
    driven by a scripted-but-real fake client/tool-runner against REAL
    OrchestratorTools (not mocks) -- proving the ACTUAL U22/U5
    implementations, per the execution note."""

    # -- 2. execute_work's gate denies -> declined, reply names the reason

    def test_gate_denies_execute_work_and_the_reply_names_the_reason(self):
        intent = _shipping_intent()
        coordinator = StubCoordinator(opportunities=[{"id": "task-1"}])
        gate = make_gate(callback=auto_deny_callback, under="1", ceiling="100")
        tools = make_real_tools(gate, coordinator=coordinator)
        script = [
            ("discover_candidates", {"capability": SHIPPING_CAP}),
            ("rank_candidates", {"candidates": shipping_candidates()}),
            ("request_terms",
             {"app_id": "shipping", "capability": SHIPPING_CAP}),
            ("execute_work",
             {"app_id": "shipping", "capability": SHIPPING_CAP,
              "cost": "5"}),
        ]
        # No scripted final text: forces the fallback reply, composed
        # from the honestly-derived state (mirrors the deterministic
        # path's compose_reply usage).
        client = FakeClaudeClient(intent, script, final_text=None)
        agent = make_agent(tools, gate, brain=ClaudeBrain(client=client))

        result = agent.handle_request("Necesito enviar un paquete a Santiago")

        assert result.status == "declined"
        assert "denied by approval callback" in result.reply
        assert coordinator.bids == []
        assert result.evidence["decision"]["approved"] is False

    # -- 3. discover_candidates empty, nothing else called -> no_candidate

    def test_empty_discovery_forces_a_short_no_candidate_reply(self):
        intent = _shipping_intent()
        gate = make_gate()
        tools = make_real_tools(gate, federation=StubFederation({}))
        script = [("discover_candidates", {"capability": SHIPPING_CAP})]
        client = FakeClaudeClient(
            intent,
            script,
            final_text=(
                "Estimado usuario, lamentablemente no hay proveedores "
                "disponibles. Si necesita ayuda adicional, estoy aquí para "
                "ayudarle. Atentamente, su asistente de concierge."
            ),
        )
        agent = make_agent(tools, gate, brain=ClaudeBrain(client=client))

        result = agent.handle_request("Necesito enviar un paquete a Santiago")

        assert result.status == "no_candidate"
        assert result.reply == (
            "No encontré un agente disponible. No se realizó ningún cargo."
        )

    # -- 4. max_iterations exhausted, no terminal text/outcome -> failed,
    #       never a fabricated "done"

    def test_no_terminal_outcome_and_no_final_text_is_honestly_failed(self):
        intent = _shipping_intent()
        gate = make_gate()
        tools = make_real_tools(gate)
        script = [
            ("discover_candidates", {"capability": SHIPPING_CAP}),
            ("rank_candidates", {"candidates": shipping_candidates()}),
            ("request_terms",
             {"app_id": "shipping", "capability": SHIPPING_CAP}),
        ]
        client = FakeClaudeClient(intent, script, final_text=None)
        agent = make_agent(tools, gate, brain=ClaudeBrain(client=client))

        result = agent.handle_request("Necesito enviar un paquete a Santiago")

        assert result.status == "failed"
        assert result.reply  # still a courteous fallback, never empty

    # -- 5. precedence: an earlier credential decline does not shadow a
    #       LATER real execution -> done

    def test_earlier_credential_decline_does_not_shadow_a_later_execution(
        self,
    ):
        intent = _shipping_intent()

        def approve_execute_only(action, cost, details=None):
            return action.startswith("execute:")

        gate = make_gate(
            callback=approve_execute_only, under="1", ceiling="100"
        )
        coordinator = StubCoordinator(opportunities=[{"id": "task-1"}])
        tools = make_real_tools(gate, coordinator=coordinator)
        script = [
            ("discover_candidates", {"capability": SHIPPING_CAP}),
            ("rank_candidates", {"candidates": shipping_candidates()}),
            ("request_terms",
             {"app_id": "shipping", "capability": SHIPPING_CAP}),
            ("request_credential_access",
             {"credential_id": "cred-1", "cost": "5"}),  # denied
            ("execute_work",
             {"app_id": "shipping", "capability": SHIPPING_CAP,
              "cost": "0"}),  # approved and executed
        ]
        client = FakeClaudeClient(intent, script, final_text="Listo.")
        agent = make_agent(tools, gate, brain=ClaudeBrain(client=client))

        result = agent.handle_request("Necesito enviar un paquete a Santiago")

        # KTD2 precedence: done wins over an earlier-recorded decline.
        assert result.status == "done"
        assert coordinator.bids == [(
            "shipping", "task-1",
            "handled by agent:orchestrator on behalf of the user",
        )]

    # -- 6. cumulative ceiling through the tool-runner itself: two
    #       execute_work calls whose sum crosses hard_ceiling -> the
    #       second is refused on the running total (R12)

    def test_cumulative_spend_across_two_scripted_execute_work_calls(self):
        intent = _shipping_intent()
        gate = make_gate(
            callback=always_approve_callback, under="1", ceiling="15"
        )
        coordinator = StubCoordinator(opportunities=[{"id": "task-1"}])
        tools = make_real_tools(gate, coordinator=coordinator)
        script = [
            ("discover_candidates", {"capability": SHIPPING_CAP}),
            ("rank_candidates", {"candidates": shipping_candidates()}),
            ("request_terms",
             {"app_id": "shipping", "capability": SHIPPING_CAP}),
            ("execute_work",
             {"app_id": "shipping", "capability": SHIPPING_CAP,
              "cost": "8"}),
            ("execute_work",
             {"app_id": "shipping", "capability": SHIPPING_CAP,
              "cost": "8"}),
        ]
        client = FakeClaudeClient(intent, script, final_text="Listo.")
        agent = make_agent(tools, gate, brain=ClaudeBrain(client=client))

        result = agent.handle_request("Necesito enviar un paquete a Santiago")

        assert result.status == "done"  # the FIRST call executed
        # Only ONE bid ever landed: the second call was refused on the
        # running total (8 + 8 = 16 > hard_ceiling 15), not silently
        # approved just because 8 alone would pass.
        assert len(coordinator.bids) == 1
        execute_outputs = [
            json.loads(output)
            for name, output in client.runner.tool_outputs
            if name == "execute_work"
        ]
        assert len(execute_outputs) == 2
        assert execute_outputs[0]["executed"] is True
        assert execute_outputs[1]["executed"] is False
        assert "hard ceiling" in execute_outputs[1]["outcome"]

    # -- 7. tracker isolation: two handle_request calls against the SAME
    #       OrchestratorTools instance never leak cost/outcome state

    def test_second_request_on_the_same_tools_instance_starts_fresh(self):
        gate = make_gate(callback=always_approve_callback, under="1",
                          ceiling="100")
        coordinator = StubCoordinator(opportunities=[{"id": "task-1"}])
        tools = make_real_tools(gate, coordinator=coordinator)

        first_script = [
            ("discover_candidates", {"capability": SHIPPING_CAP}),
            ("rank_candidates", {"candidates": shipping_candidates()}),
            ("request_terms",
             {"app_id": "shipping", "capability": SHIPPING_CAP}),
            ("execute_work",
             {"app_id": "shipping", "capability": SHIPPING_CAP,
              "cost": "5"}),
        ]
        first_client = FakeClaudeClient(
            _shipping_intent(), first_script, final_text="Listo."
        )
        # ONE agent, reused for both requests (its brain is swapped
        # between them) -- this is the SAME OrchestratorTools instance
        # AND the same OrchestratorAgent, so it also proves the U21-U26
        # cached-tool-list invariant (commit 46ce3b7) still holds across
        # two handle_request calls: _get_beta_tools() is built once, not
        # rebuilt per request.
        agent = make_agent(tools, gate, brain=ClaudeBrain(client=first_client))
        cache_before = agent._get_beta_tools()

        first_result = agent.handle_request(
            "Necesito enviar un paquete a Santiago"
        )
        assert first_result.status == "done"
        assert tools._outcome.running_cost == Decimal("5")

        # The cached tool list/closures are UNCHANGED after a request --
        # same list object, same wrapper objects inside it (identity, not
        # just equality) -- proving the cache was reused, not rebuilt.
        cache_after_first = agent._get_beta_tools()
        assert cache_after_first is cache_before
        assert [id(tool) for tool in cache_after_first] == [
            id(tool) for tool in cache_before
        ]

        # A second, INDEPENDENT request against the SAME tools instance
        # (and the SAME agent/brain-swapped-in-place), scripted to find
        # nothing -- must NOT inherit the first request's executed/cost
        # state.
        second_client = FakeClaudeClient(
            _shipping_intent(),
            script=[("discover_candidates", {"capability": SHIPPING_CAP})],
            final_text=None,
        )
        agent.brain = ClaudeBrain(client=second_client)
        tools.federation = StubFederation({})  # nothing found this time

        second_result = agent.handle_request(
            "Necesito enviar un paquete a Santiago"
        )

        assert second_result.status == "no_candidate"
        # The tracker was reset: no leaked "executed" flag, no leaked
        # cumulative cost from the first request.
        assert tools._outcome.executed is False
        assert tools._outcome.running_cost == Decimal("0")
        # And the first request's bid is still the ONLY bid ever made.
        assert len(coordinator.bids) == 1

        # Still the SAME cached tool list after the second request too --
        # the cache survives across BOTH requests, only the tracker's
        # contents (on `tools`) varied between them (KTD2).
        assert agent._get_beta_tools() is cache_before
