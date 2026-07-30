"""Tests for the orchestrator tool set (unit U22).

Covers the plan's seven scenarios:

1. ``discover_candidates`` against a real ephemeral Registry with a
   registered app -> that app comes back as a normalized candidate.
2. ``discover_candidates`` for an unknown capability -> empty list.
3. ``rank_candidates`` orders higher reputation first; price breaks ties.
4. ``request_terms`` sends a SIGNED P2P request against an ephemeral
   marketplace running with ``require_signatures=True`` and returns the
   terms derived from the work-discovery/bid flow (the rails expose no
   dedicated "quote" endpoint; terms are the ``proposed_terms`` carried
   on bids -- see ``OrchestratorTools.request_terms``).
5. ``request_credential_access`` with a denying gate -> ``{"granted":
   False}`` and NO vault call ever happens (spy vault stays empty).
6. ``request_credential_access`` with an approving gate and a real
   ephemeral Vault holding a valid grant -> granted access (gate ->
   vault chain), visible in the Vault audit trail.
7. Every ``@beta_tool`` wrapper returns JSON-serializable output and
   carries a generated schema (``to_dict``).

Integration-lite tests follow the repo's ephemeral-port fixture pattern
(tests/integration/test_federation_discovery.py etc.): real servers on
``port=0``, never fixed ports.
"""

import json
import threading
from decimal import Decimal

import pytest
import requests

from agents.orchestrator.approval import (
    ApprovalGate,
    SpendPolicy,
    always_approve_callback,
    auto_deny_callback,
)
from agents.orchestrator.tools import (
    AGENT_CANDIDATE_OUTCOME,
    OrchestratorTools,
    build_beta_tools,
    build_execute_work_tool,
)
from libs import signing
from libs.agent_coordination import AgentCoordinationError
from libs.p2p_client import P2PError
from libs.session import SessionContext
from registry.app import make_server as make_registry_server
from apps.marketplace.server.app import make_server as make_marketplace_server
from vault.app import make_server as make_vault_server

TIMEOUT = 5.0
MARKETPLACE_CAP = "marketplace.tasks"


# ---------------------------------------------------------------------------
# Server plumbing (ephemeral ports only, U9/U10-test style)
# ---------------------------------------------------------------------------


def _start(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def _url(server):
    host, port = server.server_address[:2]
    return "http://%s:%d" % (host, port)


@pytest.fixture
def registry():
    server = make_registry_server(port=0)
    _start(server)
    yield _url(server)
    server.shutdown()
    server.server_close()


@pytest.fixture
def vault_url():
    # The vault's own local audit log is gone (KTD3): GET /audit PROXIES to
    # the central Audit & Compliance service, so audit-observing tests need a
    # real ephemeral audit service wired via audit_url (same pattern as
    # tests/vault/test_credential_access.py).
    from audit.app import make_server as make_audit_server

    audit_server = make_audit_server(port=0)
    _start(audit_server)
    server = make_vault_server(port=0, audit_url=_url(audit_server))
    _start(server)
    yield _url(server)
    server.shutdown()
    server.server_close()
    audit_server.shutdown()
    audit_server.server_close()


@pytest.fixture
def marketplace_signed(registry):
    """Marketplace with signature enforcement ON, wired to the registry."""
    server = make_marketplace_server(
        port=0, registry_url=registry, require_signatures=True
    )
    _start(server)
    yield _url(server)
    server.shutdown()
    server.server_close()


def _register_app(registry_url, app_id, endpoint, capabilities, **flags):
    payload = {
        "app_id": app_id,
        "app_endpoint": endpoint,
        "p2p_endpoint": endpoint,
        "capabilities": capabilities,
    }
    payload.update(flags)
    resp = requests.post(
        "%s/apps/register" % registry_url, json=payload, timeout=TIMEOUT
    )
    assert resp.status_code == 200, resp.text


def _register_principal_with_key(registry_url, principal_id, public_key):
    resp = requests.post(
        "%s/auth/register" % registry_url,
        json={"principal_id": principal_id, "public_key": public_key},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text


def make_session():
    """A fresh principal identity + signed SessionContext (MVP convention:
    the principal_id IS the principal's base64 public key)."""
    principal = signing.generate_keypair()
    principal_id = principal.public_key_b64()
    return SessionContext.create(principal_id, principal.signing_key)


def _create_task(marketplace_url, author, description):
    resp = requests.post(
        "%s/api/tasks" % marketplace_url,
        json={"principal_id": author, "description": description},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["task"]


# ---------------------------------------------------------------------------
# Test doubles for the pure/stubbed scenarios
# ---------------------------------------------------------------------------


class StubFederation(object):
    def __init__(self, apps_by_capability):
        self.apps_by_capability = apps_by_capability

    def discover_apps(self, capability=None):
        return list(self.apps_by_capability.get(capability, []))


class StubMarketplace(object):
    def __init__(self, agents_by_capability):
        self.agents_by_capability = agents_by_capability

    def search_agents(self, capability, min_reputation=None):
        return list(self.agents_by_capability.get(capability, []))


class SpyVault(object):
    """Vault client double recording every access request."""

    def __init__(self, response=None):
        self.calls = []
        self.response = response or {
            "access_granted": True, "status_code": 200,
        }

    def request_access(self, credential_id, agent_principal_id):
        self.calls.append((credential_id, agent_principal_id))
        return dict(self.response)


def _deny_gate():
    """Gate where every cost lands in the gray zone and is DENIED."""
    return ApprovalGate(
        SpendPolicy(
            auto_approve_under=Decimal("0"),
            hard_ceiling=Decimal("100"),
        ),
        auto_deny_callback,
        audit_client=_NullAudit(),
    )


def _approve_gate():
    return ApprovalGate(
        SpendPolicy(
            auto_approve_under=Decimal("0"),
            hard_ceiling=Decimal("100"),
        ),
        always_approve_callback,
        audit_client=_NullAudit(),
    )


class _NullAudit(object):
    def log(self, *args, **kwargs):
        pass


class SpyCoordinator(object):
    """AgentCoordinator double for execute_work (U5): records
    discover_work/submit_bid calls, optionally raising ``raise_on_submit``
    / ``raise_on_discover`` to simulate a rail failure mid-flow."""

    def __init__(self, opportunities=None, raise_on_submit=None,
                 raise_on_discover=None):
        self.discover_calls = []
        self.bids = []
        self._opportunities = (
            [{"id": "task-1"}] if opportunities is None else opportunities
        )
        self._raise_on_submit = raise_on_submit
        self._raise_on_discover = raise_on_discover

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


class _UnreachableGate(object):
    """A gate whose ``require`` fails the test if it is ever called --
    proves execute_work's kind/opportunity short-circuits happen BEFORE
    the gate is consulted (only a real, self-discovered opportunity
    reaches the gate, U5/KTD6)."""

    policy = SpendPolicy(
        auto_approve_under=Decimal("0"), hard_ceiling=Decimal("100")
    )

    def require(self, action, cost, details=None):
        raise AssertionError(
            "gate.require must not be called without a self-discovered "
            "opportunity to execute"
        )


# ---------------------------------------------------------------------------
# 1-2. discover_candidates (integration-lite: real ephemeral Registry)
# ---------------------------------------------------------------------------


class TestDiscoverCandidates:
    def test_registered_app_is_discovered_as_candidate(self, registry):
        _register_app(
            registry, "marketplace", "http://127.0.0.1:59990",
            [MARKETPLACE_CAP, "p2p.ping"],
        )
        tools = OrchestratorTools(registry_url=registry)
        candidates = tools.discover_candidates(MARKETPLACE_CAP)
        assert [
            (c["id"], c["kind"]) for c in candidates
        ] == [("marketplace", "app")]
        # Normalized shape: every candidate carries a reputation slot.
        assert "reputation" in candidates[0]

    def test_unknown_capability_is_empty_list_not_error(self, registry):
        _register_app(
            registry, "marketplace", "http://127.0.0.1:59990",
            [MARKETPLACE_CAP],
        )
        tools = OrchestratorTools(registry_url=registry)
        assert tools.discover_candidates("does.not.exist") == []

    def test_union_of_federation_and_marketplace(self):
        """Apps and agents are merged into ONE normalized candidate list."""
        tools = OrchestratorTools(
            federation_client=StubFederation({
                MARKETPLACE_CAP: [{"app_id": "marketplace"}],
            }),
            marketplace_client=StubMarketplace({
                MARKETPLACE_CAP: [{
                    "principal_id": "agent:worker",
                    "reputation": {
                        "tasks_verified": 3,
                        "tasks_rejected": 0,
                        "verification_rate": 1.0,
                    },
                }],
            }),
        )
        candidates = tools.discover_candidates(MARKETPLACE_CAP)
        kinds = {(c["id"], c["kind"]) for c in candidates}
        assert kinds == {("marketplace", "app"), ("agent:worker", "agent")}
        agent = next(c for c in candidates if c["kind"] == "agent")
        assert agent["reputation"]["verification_rate"] == 1.0
        assert agent["reputation"]["tasks_verified"] == 3


# ---------------------------------------------------------------------------
# 3. rank_candidates (pure logic)
# ---------------------------------------------------------------------------


class TestRankCandidates:
    def test_higher_reputation_first(self):
        tools = OrchestratorTools()
        low = {"id": "a", "kind": "agent",
               "reputation": {"verification_rate": 0.5, "tasks_verified": 9}}
        high = {"id": "b", "kind": "agent",
                "reputation": {"verification_rate": 1.0, "tasks_verified": 1}}
        neutral = {"id": "c", "kind": "app", "reputation": None}
        ranked = tools.rank_candidates([low, neutral, high])
        assert [c["id"] for c in ranked] == ["b", "a", "c"]

    def test_tasks_verified_breaks_rate_ties(self):
        tools = OrchestratorTools()
        few = {"id": "few", "kind": "agent",
               "reputation": {"verification_rate": 1.0, "tasks_verified": 1}}
        many = {"id": "many", "kind": "agent",
                "reputation": {"verification_rate": 1.0, "tasks_verified": 7}}
        ranked = tools.rank_candidates([few, many])
        assert [c["id"] for c in ranked] == ["many", "few"]

    def test_price_breaks_full_reputation_ties(self):
        tools = OrchestratorTools()
        rep = {"verification_rate": 1.0, "tasks_verified": 2}
        cheap = {"id": "cheap", "kind": "agent",
                 "reputation": dict(rep), "price": 2.0}
        pricey = {"id": "pricey", "kind": "agent",
                  "reputation": dict(rep), "price": 9.0}
        unpriced = {"id": "unpriced", "kind": "agent",
                    "reputation": dict(rep)}
        ranked = tools.rank_candidates([pricey, unpriced, cheap])
        # Price ascending; candidates with no price sort after priced ones.
        assert [c["id"] for c in ranked] == ["cheap", "pricey", "unpriced"]

    def test_speed_is_the_last_tie_breaker(self):
        tools = OrchestratorTools()
        rep = {"verification_rate": 0.8, "tasks_verified": 4}
        slow = {"id": "slow", "kind": "agent",
                "reputation": dict(rep), "price": 3.0, "speed": 60.0}
        fast = {"id": "fast", "kind": "agent",
                "reputation": dict(rep), "price": 3.0, "speed": 5.0}
        ranked = tools.rank_candidates([slow, fast])
        assert [c["id"] for c in ranked] == ["fast", "slow"]

    def test_does_not_mutate_input(self):
        tools = OrchestratorTools()
        original = [
            {"id": "a", "kind": "app", "reputation": None},
            {"id": "b", "kind": "agent",
             "reputation": {"verification_rate": 1.0, "tasks_verified": 1}},
        ]
        snapshot = list(original)
        tools.rank_candidates(original)
        assert original == snapshot


# ---------------------------------------------------------------------------
# 4. request_terms (signed P2P against a real signed marketplace)
# ---------------------------------------------------------------------------


class TestRequestTerms:
    def test_signed_request_returns_terms_from_bid_flow(
        self, registry, marketplace_signed
    ):
        _register_app(
            registry, "marketplace", marketplace_signed, [MARKETPLACE_CAP]
        )
        # The orchestrator's own signed identity.
        orchestrator_session = make_session()
        _register_principal_with_key(
            registry,
            orchestrator_session.principal_id,
            orchestrator_session.principal_id,
        )
        # A worker agent bids on an open task (signed, via the same rails).
        worker_session = make_session()
        _register_principal_with_key(
            registry, worker_session.principal_id,
            worker_session.principal_id,
        )
        task = _create_task(
            marketplace_signed, "user:author", "enviar un paquete"
        )
        from libs.agent_coordination import AgentCoordinator
        AgentCoordinator(
            registry, worker_session.principal_id, session=worker_session
        ).submit_bid("marketplace", task["id"], "2 credits, done today")

        tools = OrchestratorTools(
            registry_url=registry,
            agent_principal_id=orchestrator_session.principal_id,
            session=orchestrator_session,
        )
        # Without a task_id: discovery leg (signed list.work_opportunities).
        offers = tools.request_terms("marketplace", MARKETPLACE_CAP)
        assert offers["app_id"] == "marketplace"
        assert [o["id"] for o in offers["opportunities"]] == [task["id"]]

        # With a task_id: terms are the proposed_terms of the task's bids.
        terms = tools.request_terms(
            "marketplace", MARKETPLACE_CAP, {"task_id": task["id"]}
        )
        assert terms["task_id"] == task["id"]
        assert [t["terms"] for t in terms["terms"]] == [
            "2 credits, done today"
        ]
        assert terms["terms"][0]["agent"] == worker_session.principal_id

    def test_unsigned_request_is_rejected_by_signed_app(
        self, registry, marketplace_signed
    ):
        """Control: without a session the same call fails -> the success
        above proves the tools' P2P request really was signed."""
        _register_app(
            registry, "marketplace", marketplace_signed, [MARKETPLACE_CAP]
        )
        _register_principal_with_key(registry, "agent:unsigned", None)
        tools = OrchestratorTools(
            registry_url=registry, agent_principal_id="agent:unsigned"
        )
        with pytest.raises(P2PError):
            tools.request_terms("marketplace", MARKETPLACE_CAP)

    def test_agent_kind_candidate_returns_courteous_outcome_not_raising(self):
        """An agent-kind ``app_id`` is never a registered app, so the
        coordinator's discover_work/discover_app chain would otherwise
        raise a raw AgentCoordinationError/P2PError (R4, KTD3). No
        coordinator/registry is even configured here -- the ``kind``
        guard must short-circuit before anything would try to reach one."""
        tools = OrchestratorTools()
        result = tools.request_terms(
            "agent:veteran", MARKETPLACE_CAP, kind="agent"
        )
        assert result["outcome"] == AGENT_CANDIDATE_OUTCOME
        assert result["opportunities"] == []
        assert result["terms"] == []

    def test_beta_tool_wrapper_threads_kind_through_to_courteous_outcome(self):
        """The @beta_tool wrapper (the tool-runner's own call surface)
        gets the identical non-raising, courteous result when the model
        passes along an agent-kind candidate's ``kind``."""
        tools = OrchestratorTools()
        by_name = {w.name: w for w in build_beta_tools(tools)}
        payload = json.loads(
            by_name["request_terms"].func(
                app_id="agent:veteran",
                capability=MARKETPLACE_CAP,
                kind="agent",
            )
        )
        assert payload["outcome"] == AGENT_CANDIDATE_OUTCOME


# ---------------------------------------------------------------------------
# 5-6. request_credential_access (gate -> vault chain)
# ---------------------------------------------------------------------------


class TestRequestCredentialAccess:
    def test_gate_denial_returns_granted_false_and_never_touches_vault(self):
        spy = SpyVault()
        tools = OrchestratorTools(
            gate=_deny_gate(),
            vault_client=spy,
            agent_principal_id="agent:orchestrator",
        )
        result = tools.request_credential_access("cred-1", cost=Decimal("5"))
        assert result["granted"] is False
        assert result["reason"]
        assert spy.calls == []  # NO vault access occurred

    def test_no_gate_configured_fails_closed(self):
        spy = SpyVault()
        tools = OrchestratorTools(vault_client=spy)
        result = tools.request_credential_access("cred-1")
        assert result["granted"] is False
        assert spy.calls == []

    def test_vault_error_is_returned_not_raised(self):
        class BrokenVault(object):
            def request_access(self, credential_id, agent_principal_id):
                raise requests.ConnectionError("vault down")

        tools = OrchestratorTools(
            gate=_approve_gate(), vault_client=BrokenVault()
        )
        result = tools.request_credential_access("cred-1")
        assert result["granted"] is False
        assert "vault" in result["reason"]

    def test_approved_gate_with_valid_grant_gets_access(self, vault_url):
        """Real ephemeral Vault: gate approves -> vault grants -> access."""
        owner = "user:owner"
        agent_id = "agent:orchestrator"
        resp = requests.post(
            "%s/credentials" % vault_url,
            json={
                "name": "api-key",
                "credential_type": "api_key",
                "encrypted_data": "ZmFrZS1jaXBoZXJ0ZXh0",
                "nonce": "ZmFrZS1ub25jZQ==",
                "user_principal_id": owner,
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
        credential_id = resp.json()["credential_id"]
        resp = requests.post(
            "%s/credentials/%s/grants" % (vault_url, credential_id),
            json={
                "agent_principal_id": agent_id,
                "scope": "read",
                "granted_by": owner,
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text

        tools = OrchestratorTools(
            vault_url=vault_url,
            gate=_approve_gate(),
            agent_principal_id=agent_id,
        )
        result = tools.request_credential_access(
            credential_id, cost=Decimal("1")
        )
        assert result["granted"] is True
        assert result["vault_response"]["access_granted"] is True
        # The central audit trail (proxied through the vault, KTD3) recorded
        # the granted access — new entry shape: activity_type/resource_id.
        audit = requests.get(
            "%s/audit" % vault_url,
            params={"principal_id": agent_id},
            timeout=TIMEOUT,
        ).json()["entries"]
        assert any(
            e["activity_type"] == "credential.access"
            and e["status"] == "granted"
            and e["resource_id"] == credential_id
            for e in audit
        )

    def test_denied_gate_leaves_no_vault_audit_trail(self, vault_url):
        """Same real Vault, denying gate: the vault never hears about it."""
        agent_id = "agent:orchestrator"
        tools = OrchestratorTools(
            vault_url=vault_url,
            gate=_deny_gate(),
            agent_principal_id=agent_id,
        )
        result = tools.request_credential_access(
            "cred-anything", cost=Decimal("5")
        )
        assert result["granted"] is False
        # The central audit store is DB-backed and shared across ephemeral
        # service instances, so assert THIS attempt left no trail (no entry
        # for this credential), not that the whole store is empty.
        audit = requests.get(
            "%s/audit" % vault_url,
            params={"principal_id": agent_id},
            timeout=TIMEOUT,
        ).json()["entries"]
        assert not any(e["resource_id"] == "cred-anything" for e in audit)


# ---------------------------------------------------------------------------
# report_to_user
# ---------------------------------------------------------------------------


class TestReportToUser:
    def test_reporter_hook_is_called(self):
        reported = []
        tools = OrchestratorTools(reporter=reported.append)
        result = tools.report_to_user("Su paquete está en camino.")
        assert reported == ["Su paquete está en camino."]
        assert result == {
            "reported": True, "message": "Su paquete está en camino.",
        }


# ---------------------------------------------------------------------------
# 7. @beta_tool wrappers (one implementation, Tool-Runner surface)
# ---------------------------------------------------------------------------


class TestBetaToolWrappers:
    @pytest.fixture
    def tools(self):
        return OrchestratorTools(
            federation_client=StubFederation({
                MARKETPLACE_CAP: [{"app_id": "marketplace"}],
            }),
            marketplace_client=StubMarketplace({MARKETPLACE_CAP: []}),
            gate=_deny_gate(),
            vault_client=SpyVault(),
            reporter=lambda message: None,
        )

    def test_every_wrapper_has_a_generated_schema(self, tools):
        wrappers = build_beta_tools(tools)
        names = {w.name for w in wrappers}
        assert names == {
            "discover_candidates",
            "rank_candidates",
            "request_terms",
            "request_credential_access",
            "report_to_user",
        }
        for wrapper in wrappers:
            definition = wrapper.to_dict()
            assert definition["name"] == wrapper.name
            assert definition["description"]
            schema = definition["input_schema"]
            assert schema["type"] == "object"
            assert isinstance(schema.get("properties"), dict)

    def test_wrappers_return_json_serializable_output(self, tools):
        by_name = {w.name: w for w in build_beta_tools(tools)}

        outputs = {
            "discover_candidates": by_name["discover_candidates"].func(
                capability=MARKETPLACE_CAP
            ),
            "rank_candidates": by_name["rank_candidates"].func(
                candidates=[
                    {"id": "a", "kind": "app", "reputation": None},
                    {"id": "b", "kind": "agent",
                     "reputation": {"verification_rate": 1.0,
                                    "tasks_verified": 2}},
                ]
            ),
            "request_credential_access": by_name[
                "request_credential_access"
            ].func(credential_id="cred-1", cost="5"),
            "report_to_user": by_name["report_to_user"].func(
                message="hola"
            ),
        }
        for name, output in outputs.items():
            json.dumps(output)  # must not raise
            # Wrappers return JSON text: parseable back into structure.
            parsed = json.loads(output)
            assert parsed is not None, name

        # Denied credential access surfaced as data, never an exception.
        denied = json.loads(outputs["request_credential_access"])
        assert denied["granted"] is False

    def test_credential_wrapper_validates_cost_without_raising(self, tools):
        by_name = {w.name: w for w in build_beta_tools(tools)}
        output = by_name["request_credential_access"].func(
            credential_id="cred-1", cost="not-a-number"
        )
        parsed = json.loads(output)
        assert parsed["granted"] is False

    @pytest.mark.parametrize("bad_cost", ["NaN", "-NaN", "sNaN", "Infinity",
                                           "-Infinity"])
    def test_credential_wrapper_rejects_non_finite_cost_without_raising(
        self, tools, bad_cost,
    ):
        """Decimal("NaN")/"Infinity" construct successfully, so the R6
        auto-approve-floor's max() comparison right after parsing would
        raise decimal.InvalidOperation past the sanitizing try/except if
        non-finite values weren't rejected up front."""
        by_name = {w.name: w for w in build_beta_tools(tools)}
        output = by_name["request_credential_access"].func(
            credential_id="cred-1", cost=bad_cost
        )
        parsed = json.loads(output)
        assert parsed["granted"] is False
        assert "invalid cost" in parsed["reason"]
        assert "cost" in parsed["reason"]

    def test_wrapper_strips_vault_response_on_a_grant(self):
        """Regression (R2/P1): the vault's sealed ciphertext envelope must
        never reach the LLM, even on a grant."""
        vault = SpyVault(response={
            "access_granted": True, "status_code": 200,
            "ciphertext": "sealed-envelope-bytes",
        })
        tools = OrchestratorTools(
            gate=_approve_gate(),
            vault_client=vault,
            agent_principal_id="agent:orchestrator",
        )
        by_name = {w.name: w for w in build_beta_tools(tools)}
        parsed = json.loads(
            by_name["request_credential_access"].func(
                credential_id="cred-1", cost="1"
            )
        )
        assert parsed["granted"] is True
        assert "vault_response" not in parsed

    def test_raw_method_still_carries_vault_response(self):
        """The strip above is wrapper-scoped ONLY -- direct/RuleBrain
        callers and the agent's own evidence still get the full result
        (including vault_response) from the underlying method."""
        vault = SpyVault(response={
            "access_granted": True, "status_code": 200,
            "ciphertext": "sealed-envelope-bytes",
        })
        tools = OrchestratorTools(
            gate=_approve_gate(),
            vault_client=vault,
            agent_principal_id="agent:orchestrator",
        )
        result = tools.request_credential_access("cred-1", cost=Decimal("1"))
        assert result["granted"] is True
        assert result["vault_response"]["access_granted"] is True

    def test_wrapper_delegates_to_the_single_implementation(self, tools):
        """RuleBrain/tests call the class method; the Tool Runner calls the
        wrapper -- both must hit the SAME implementation."""
        by_name = {w.name: w for w in build_beta_tools(tools)}
        direct = tools.discover_candidates(MARKETPLACE_CAP)
        via_wrapper = json.loads(
            by_name["discover_candidates"].func(capability=MARKETPLACE_CAP)
        )
        assert via_wrapper == direct


# ---------------------------------------------------------------------------
# U5: execute_work -- self-grounded target, gated, shared bid logic
# ---------------------------------------------------------------------------


def _app_only_tools(coordinator, gate, agent_principal_id="agent:orchestrator"):
    """OrchestratorTools wired so discover_candidates surfaces exactly one
    app-kind candidate ("marketplace") for MARKETPLACE_CAP."""
    return OrchestratorTools(
        federation_client=StubFederation({
            MARKETPLACE_CAP: [{"app_id": "marketplace"}],
        }),
        marketplace_client=StubMarketplace({}),
        coordinator=coordinator,
        gate=gate,
        agent_principal_id=agent_principal_id,
    )


class TestExecuteWork:
    # -- 1. gate denies -> no submit_bid call -------------------------------

    def test_gate_denial_returns_executed_false_without_submitting_a_bid(
        self,
    ):
        coordinator = SpyCoordinator(opportunities=[{"id": "task-1"}])
        tools = _app_only_tools(coordinator, gate=_deny_gate())

        result = tools.execute_work(
            "marketplace", MARKETPLACE_CAP, Decimal("5")
        )

        assert result["executed"] is False
        assert coordinator.bids == []

    # -- 2. gate approves -> bids on the SELF-discovered opportunity --------

    def test_gate_approval_bids_on_the_self_discovered_opportunity(self):
        coordinator = SpyCoordinator(opportunities=[{"id": "task-9"}])
        tools = _app_only_tools(coordinator, gate=_approve_gate())

        result = tools.execute_work(
            "marketplace", MARKETPLACE_CAP, Decimal("1")
        )

        assert result["executed"] is True
        assert coordinator.bids == [(
            "marketplace", "task-9",
            "handled by agent:orchestrator on behalf of the user",
        )]
        # The underlying method's own return value carries the raw bid
        # and task_id -- available to direct/RuleBrain callers and the
        # agent's evidence (R2 precedent: only the WRAPPER strips it).
        assert result["task_id"] == "task-9"
        assert result["bid"]["id"] == "bid-1"

    def test_beta_tool_wrapper_strips_to_executed_and_outcome_only(self):
        """Regression in the same shape as U1's R2 test: the wrapper's
        JSON output carries ONLY executed/outcome, never the raw bid
        object or a task id, even on a real, successful execution."""
        coordinator = SpyCoordinator(opportunities=[{"id": "task-9"}])
        tools = _app_only_tools(coordinator, gate=_approve_gate())

        execute_work = build_execute_work_tool(tools)
        payload = json.loads(
            execute_work.func(
                app_id="marketplace", capability=MARKETPLACE_CAP, cost="1"
            )
        )

        assert set(payload) == {"executed", "outcome"}
        assert payload["executed"] is True
        assert payload["outcome"]
        # The bid really was submitted against the tool's own discovery.
        assert coordinator.bids == [(
            "marketplace", "task-9",
            "handled by agent:orchestrator on behalf of the user",
        )]

    # -- 3. low model-claimed cost is floored, never silently approved -----

    def test_wrapper_floors_a_low_claimed_cost_against_the_policy_threshold(
        self,
    ):
        consulted = []

        def spy_callback(action, cost, details=None):
            consulted.append((action, cost))
            return True  # approve once consulted -- proves it WAS asked

        gate = ApprovalGate(
            SpendPolicy(
                auto_approve_under=Decimal("10"),
                hard_ceiling=Decimal("100"),
            ),
            spy_callback,
            audit_client=_NullAudit(),
        )
        coordinator = SpyCoordinator(opportunities=[{"id": "task-1"}])
        tools = _app_only_tools(coordinator, gate=gate)

        execute_work = build_execute_work_tool(tools)
        payload = json.loads(
            execute_work.func(
                app_id="marketplace", capability=MARKETPLACE_CAP,
                cost="0.01",
            )
        )

        assert len(consulted) == 1  # the callback WAS consulted
        assert consulted[0][1] >= Decimal("10")
        assert payload["executed"] is True

    @pytest.mark.parametrize("bad_cost", ["NaN", "-NaN", "sNaN", "Infinity",
                                           "-Infinity"])
    def test_wrapper_rejects_non_finite_cost_without_raising(self, bad_cost):
        coordinator = SpyCoordinator(opportunities=[{"id": "task-1"}])
        tools = _app_only_tools(coordinator, gate=_UnreachableGate())

        execute_work = build_execute_work_tool(tools)
        payload = json.loads(
            execute_work.func(
                app_id="marketplace", capability=MARKETPLACE_CAP,
                cost=bad_cost,
            )
        )

        assert payload["executed"] is False
        assert "invalid cost" in payload["outcome"]
        assert coordinator.bids == []

    # -- 4. agent-kind candidate / no open opportunity -> courteous, no gate

    def test_agent_kind_candidate_short_circuits_before_the_gate(self):
        coordinator = SpyCoordinator()
        tools = OrchestratorTools(
            federation_client=StubFederation({}),
            marketplace_client=StubMarketplace({
                MARKETPLACE_CAP: [{
                    "principal_id": "agent:veteran",
                    "reputation": {
                        "verification_rate": 1.0, "tasks_verified": 5,
                    },
                }],
            }),
            coordinator=coordinator,
            gate=_UnreachableGate(),
        )

        result = tools.execute_work(
            "agent:veteran", MARKETPLACE_CAP, Decimal("1")
        )

        assert result == {
            "executed": False, "outcome": AGENT_CANDIDATE_OUTCOME,
        }
        # Never even reached the coordinator rail.
        assert coordinator.discover_calls == []
        assert coordinator.bids == []

    def test_app_id_absent_from_discovery_is_rejected_before_the_gate(self):
        """An app_id NOT among this call's own discover_candidates results
        must be rejected outright, never treated as a fabricated
        {"kind": None} candidate that falls through to discover_work/
        submit_bid -- the self-grounding guarantee execute_work's own
        docstring makes must hold for app_id, not just task_id."""
        coordinator = SpyCoordinator(opportunities=[{"id": "task-1"}])
        tools = _app_only_tools(coordinator, gate=_UnreachableGate())

        result = tools.execute_work(
            "not-a-real-app", MARKETPLACE_CAP, Decimal("1")
        )

        assert result == {
            "executed": False,
            "outcome": "not-a-real-app no aparece entre los candidatos "
            "descubiertos para %s; nada fue ejecutado" % MARKETPLACE_CAP,
        }
        # Never even reached the coordinator rail -- fails closed before
        # discover_work/submit_bid, and never consults the gate either.
        assert coordinator.discover_calls == []
        assert coordinator.bids == []

    def test_no_open_opportunity_short_circuits_before_the_gate(self):
        coordinator = SpyCoordinator(opportunities=[])
        tools = _app_only_tools(coordinator, gate=_UnreachableGate())

        result = tools.execute_work(
            "marketplace", MARKETPLACE_CAP, Decimal("1")
        )

        assert result == {
            "executed": False,
            "outcome": "no hay trabajo abierto en marketplace por ahora",
        }
        assert coordinator.bids == []

    # -- 5. a rail failure while bidding is data, never an exception --------

    def test_submit_bid_rail_failure_is_returned_not_raised(self):
        coordinator = SpyCoordinator(
            opportunities=[{"id": "task-1"}],
            raise_on_submit=AgentCoordinationError(
                "task-1 was already claimed by another bidder"
            ),
        )
        tools = _app_only_tools(coordinator, gate=_approve_gate())

        result = tools.execute_work(
            "marketplace", MARKETPLACE_CAP, Decimal("1")
        )

        assert result["executed"] is False
        assert "already claimed" in result["reason"]

    def test_discover_work_rail_failure_is_returned_not_raised(self):
        """A P2PError while re-deriving the opportunity (not just while
        submitting the bid) is equally data, never an unhandled
        exception into the tool-runner loop."""
        coordinator = SpyCoordinator(
            raise_on_discover=P2PError("marketplace unreachable"),
        )
        tools = _app_only_tools(coordinator, gate=_approve_gate())

        result = tools.execute_work(
            "marketplace", MARKETPLACE_CAP, Decimal("1")
        )

        assert result["executed"] is False
        assert "unreachable" in result["reason"]

    # -- 6. _execute (deterministic) and execute_work (tool-runner) share --

    def test_execute_and_execute_work_share_the_bid_submission_result(self):
        """Proves the shared implementation (not parallel, drift-prone
        copies): the deterministic path's OrchestratorAgent._execute and
        the tool-runner path's OrchestratorTools.execute_work produce an
        identical bid result for the same candidate/opportunity."""
        from agents.orchestrator.agent import OrchestratorAgent
        from agents.orchestrator.brain import RuleBrain

        candidate = {"id": "marketplace", "kind": "app", "reputation": None}

        coordinator_a = SpyCoordinator(opportunities=[{"id": "task-1"}])
        tools_a = _app_only_tools(coordinator_a, gate=_approve_gate())
        agent = OrchestratorAgent(
            registry_url="http://registry.invalid",
            brain=RuleBrain(),
            tools=tools_a,
            gate=_approve_gate(),
            agent_id="agent:orchestrator",
        )
        via_execute = agent._execute(
            candidate, {"opportunities": [{"id": "task-1"}]}
        )

        coordinator_b = SpyCoordinator(opportunities=[{"id": "task-1"}])
        tools_b = _app_only_tools(coordinator_b, gate=_approve_gate())
        via_execute_work = tools_b.execute_work(
            "marketplace", MARKETPLACE_CAP, Decimal("1")
        )

        assert via_execute["executed"] is True
        assert via_execute_work["executed"] is True
        assert via_execute["task_id"] == via_execute_work["task_id"]
        assert via_execute["outcome"] == via_execute_work["outcome"]
        assert via_execute["bid"] == via_execute_work["bid"]
        assert coordinator_a.bids == coordinator_b.bids
