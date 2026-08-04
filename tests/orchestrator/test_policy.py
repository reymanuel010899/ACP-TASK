import json

import pytest

from agents.orchestrator.action_repository import (
    ActionRepository,
    canonical_payload_hash,
)
from agents.orchestrator.planner import descriptor_hash
from agents.orchestrator.policy import PolicyEvaluator
from agents.orchestrator.workflow_broker_dispatcher import WorkflowBrokerDispatcher
from agents.orchestrator.workflow_repository import WorkflowRepository
from libs.integrations.catalog import (
    ProviderRuntime,
    ProviderRuntimeRegistry,
    slack_definitions,
)
from services.action_broker.app import ActionBroker


NOW = 1_700_000_000
ROLLOUT = "rollout-1"


def _definition(capability_id):
    return next(
        item for item in slack_definitions()
        if item.capability_id == capability_id
    )


def _connection(definition):
    return {
        "connection_id": "conn:slack",
        "tenant_id": "org:acme",
        "status": "connected",
        "credential_id": "credential:slack",
        "credential_version": 7,
        "granted_scopes": sorted(definition.required_scopes),
        "enabled_capabilities": [definition.capability_id],
        "authority_profile": "bot",
    }


def _binding(definition, effect=None):
    effect = effect or definition.effect
    payload = (
        {"channel_id": "C1", "text": "hello"}
        if effect == "write" else {}
    )
    payload_hash = canonical_payload_hash(payload) if effect == "write" else None
    return {
        "user_principal_id": "user:alice",
        "agent_principal_id": "agent:orchestrator",
        "task_id": "revision:1:step:1",
        "tenant_id": "org:acme",
        "connection_id": "conn:slack",
        "authority_profile": "bot",
        "credential_id": "credential:slack",
        "credential_version": 7,
        "capability_id": definition.capability_id,
        "capability_version": definition.version,
        "descriptor_snapshot_hash": descriptor_hash(definition),
        "effect": effect,
        "plan_graph_hash": "graph:1",
        "workflow_revision_id": "revision:1",
        "step_id": "step:1",
        "attempt": 1,
        "approval_payload_hash": payload_hash,
        "approval_expires_at": NOW + 300 if effect == "write" else None,
        "payload_hash": payload_hash,
        "slack_connect": False,
        "data_egress": False,
        "connection_snapshot": {
            "connection_id": "conn:slack",
            "tenant_id": "org:acme",
            "capability_id": definition.capability_id,
            "capability_version": definition.version,
            "credential_version": 7,
            "effective_scopes": sorted(definition.required_scopes),
            "health": "healthy",
            "rollout_version": ROLLOUT,
            "authority_profile": "bot",
        },
    }, payload


@pytest.mark.parametrize(
    "capability_id", ["slack.channels.list", "slack.message.send"],
)
def test_bot_policy_decision_is_versioned_deterministic_and_allows_read_write(
    capability_id,
):
    definition = _definition(capability_id)
    binding, _payload = _binding(definition)
    evaluator = PolicyEvaluator(slack_definitions(), ROLLOUT)

    first = evaluator.evaluate(binding, _connection(definition), NOW)
    binding["connection_snapshot"]["effective_scopes"].reverse()
    second = evaluator.evaluate(binding, _connection(definition), NOW)

    assert first == second
    assert first["allowed"] is True
    assert first["reason"] == "allowed"
    assert first["version"] == "policy-v1"
    assert len(first["input_hash"]) == 64
    assert len(first["decision_hash"]) == 64


@pytest.mark.parametrize(
    "mutation, reason",
    [
        (lambda live, binding: live.update(tenant_id="org:other"), "tenant_mismatch"),
        (lambda live, binding: live.update(connection_id="conn:other"), "connection_mismatch"),
        (lambda live, binding: live.update(credential_version=8), "credential_mismatch"),
        (lambda live, binding: live.update(granted_scopes=[]), "missing_required_scopes"),
        # Live authority drifting away from the binding is a mismatch, not
        # an unsupported profile: the binding still says bot.
        (lambda live, binding: live.update(authority_profile="user"), "authority_profile_mismatch"),
        (lambda live, binding: binding.update(slack_connect=True), "slack_connect_denied"),
        (lambda live, binding: binding.update(data_egress=True), "data_egress_denied"),
    ],
)
def test_policy_fails_closed_for_live_authority_and_egress_drift(
    mutation, reason,
):
    definition = _definition("slack.channels.list")
    binding, _payload = _binding(definition)
    live = _connection(definition)
    mutation(live, binding)

    decision = PolicyEvaluator(
        slack_definitions(), ROLLOUT
    ).evaluate(binding, live, NOW)

    assert decision["allowed"] is False
    assert decision["reason"] == reason


def test_dispatcher_attaches_policy_only_after_live_authorization_checks(tmp_path):
    definition = _definition("slack.channels.list")
    workflows = WorkflowRepository(str(tmp_path / "workflow.sqlite"))
    actions = ActionRepository(str(tmp_path / "actions.sqlite"))
    run = workflows.create_run("org:acme", "user:alice", "goal", NOW)
    revision = workflows.create_revision(
        run["workflow_run_id"], "org:acme", "graph:1", [{
            "step_id": "channels",
            "capability_id": definition.capability_id,
            "capability_version": definition.version,
            "connection_id": "conn:slack",
            "credential_version": 7,
            "descriptor_snapshot_hash": descriptor_hash(definition),
            "input_hash": "input:1",
            "input": {},
            "depends_on": [],
            "effect": "read",
        }], NOW,
    )
    workflows.authorize_requested_read(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:acme", "graph:1", "user:alice", NOW,
    )
    claim = workflows.claim_ready_step(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:acme", "worker", NOW, 60,
    )
    step = workflows.get_revision(
        run["workflow_run_id"], revision["workflow_revision_id"], "org:acme"
    )["steps"][0]
    connection = _connection(definition)

    class Connections:
        def get_installation(self, connection_id, tenant_id):
            assert (connection_id, tenant_id) == ("conn:slack", "org:acme")
            return dict(connection)

    class Broker:
        def execute(self, _lease, binding, _payload):
            assert binding["policy_decision"]["allowed"] is True
            assert binding["authority_profile"] == "bot"
            return 200, {"receipt": {"channels": []}}

    result = WorkflowBrokerDispatcher(
        actions, Broker(), Connections(), workflows, clock=lambda: NOW,
        rollout_version=ROLLOUT,
        policy_evaluator=PolicyEvaluator(slack_definitions(), ROLLOUT),
    )(step, claim)

    assert result["receipt"] == {"channels": []}


class _Vault:
    def __init__(self):
        self.calls = 0

    def use_managed_oauth(self, _credential_id, _identity, operation):
        self.calls += 1
        return operation(json.dumps({
            "access_token": "xoxb-test",
            "granted_scopes": ["channels:read"],
        }).encode("utf-8"))


class _SlackConnector:
    pass


class _SlackExecutor:
    def __init__(self):
        self.calls = 0

    def read(self, _capability, _payload, _context):
        self.calls += 1
        return {"channels": [], "next_cursor": None, "partial": False}


@pytest.mark.parametrize("drift", ["scope", "credential", "rollout", "tenant", "profile"])
def test_broker_recomputes_dynamic_policy_and_blocks_toctou_before_provider(
    tmp_path, drift,
):
    definition = _definition("slack.channels.list")
    initial = _connection(definition)
    live = dict(initial)
    live["granted_scopes"] = list(initial["granted_scopes"])
    binding, payload = _binding(definition)
    dispatcher_policy = PolicyEvaluator(slack_definitions(), ROLLOUT)
    binding["policy_decision"] = dispatcher_policy.evaluate(
        binding, initial, NOW
    )
    if drift == "scope":
        live["granted_scopes"] = []
    elif drift == "credential":
        live["credential_version"] = 8
    elif drift == "tenant":
        live["tenant_id"] = "org:other"
    elif drift == "profile":
        live["authority_profile"] = "user"

    broker_policy = PolicyEvaluator(
        slack_definitions(), "rollout-2" if drift == "rollout" else ROLLOUT,
    )
    actions = ActionRepository(str(tmp_path / "actions.sqlite"))
    lease = actions.issue_lease(
        "user:alice", "agent:orchestrator", binding["task_id"],
        "credential:slack", [definition.capability_id], NOW + 60,
        workflow_revision_id="revision:1", step_id="step:1",
        plan_graph_hash="graph:1", connection_id="conn:slack", attempt=1,
    )
    vault = _Vault()
    executor = _SlackExecutor()
    runtime = ProviderRuntimeRegistry((ProviderRuntime(
        provider="slack", connector=_SlackConnector(), executor=executor,
        definitions=(definition,),
    ),))
    broker = ActionBroker(
        actions, object(), vault, object(), clock=lambda: NOW,
        credential_authorizer=lambda _binding: True,
        runtime_registry=runtime, rollout_version=ROLLOUT,
        policy_evaluator=broker_policy,
        connection_resolver=lambda _connection_id, _tenant_id: dict(live),
    )

    status, response = broker.execute(lease, binding, payload)

    assert status == 403
    assert response["error"] == "dynamic policy decision is stale or denied"
    assert vault.calls == 0
    assert executor.calls == 0


def _personal(definition, **overrides):
    binding, _payload = _binding(definition)
    live = _connection(definition)
    for target in (binding, live, binding["connection_snapshot"]):
        target["authority_profile"] = "user"
    binding.update({
        "authority_profile_id": "authority:1",
        "slack_subject_id": "U1",
        "authority_authorization": {
            "allowed": True, "reason": "requester_is_subject",
            "authority_profile_id": "authority:1",
        },
    })
    binding.update(overrides)
    return binding, live


def test_a_user_token_dispatch_carries_proof_of_whose_token_it_is():
    definition = _definition("slack.channels.list")
    binding, live = _personal(definition)

    decision = PolicyEvaluator(slack_definitions(), ROLLOUT).evaluate(
        binding, live, NOW,
    )

    assert decision["allowed"] is True
    assert decision["reason"] == "allowed"


def test_a_delegated_user_token_is_also_accepted():
    definition = _definition("slack.channels.list")
    binding, live = _personal(definition, authority_authorization={
        "allowed": True, "reason": "delegated",
        "authority_profile_id": "authority:1",
    })

    assert PolicyEvaluator(slack_definitions(), ROLLOUT).evaluate(
        binding, live, NOW,
    )["allowed"] is True


@pytest.mark.parametrize("overrides,reason", [
    ({"authority_profile_id": None}, "personal_authority_unbound"),
    ({"slack_subject_id": None}, "personal_authority_unbound"),
    ({"authority_authorization": None}, "personal_authority_unproven"),
    ({"authority_authorization": {
        "allowed": True, "reason": "requester_is_subject",
        "authority_profile_id": "authority:other",
    }}, "personal_authority_mismatch"),
    ({"authority_authorization": {
        "allowed": False, "reason": "delegation_absent",
        "authority_profile_id": "authority:1",
    }}, "personal_authority_denied"),
    ({"authority_authorization": {
        "allowed": True, "reason": "authority_profile_disabled",
        "authority_profile_id": "authority:1",
    }}, "personal_authority_denied"),
])
def test_an_unproven_personal_authority_never_reaches_slack(overrides, reason):
    definition = _definition("slack.channels.list")
    binding, live = _personal(definition, **overrides)

    decision = PolicyEvaluator(slack_definitions(), ROLLOUT).evaluate(
        binding, live, NOW,
    )

    assert decision["allowed"] is False
    assert decision["reason"] == reason


def test_enterprise_authority_is_refused_at_the_boundary():
    definition = _definition("slack.channels.list")
    binding, live = _personal(definition)
    for target in (binding, live, binding["connection_snapshot"]):
        target["authority_profile"] = "enterprise_admin"

    decision = PolicyEvaluator(slack_definitions(), ROLLOUT).evaluate(
        binding, live, NOW,
    )

    # No qualified executor and no credential custody exist for admin.*, so
    # the refusal is named here rather than failing somewhere less visible.
    assert decision["allowed"] is False
    assert decision["reason"] == "enterprise_authority_unavailable"


def test_the_subject_is_covered_by_the_policy_hash():
    definition = _definition("slack.channels.list")
    binding, live = _personal(definition)
    evaluator = PolicyEvaluator(slack_definitions(), ROLLOUT)

    original = evaluator.evaluate(binding, live, NOW)
    swapped = evaluator.evaluate(
        dict(binding, slack_subject_id="U-someone-else"), live, NOW,
    )

    # Swapping whose token it acts as must change the decision, or an approval
    # for one person would authorise a dispatch as another.
    assert original["input_hash"] != swapped["input_hash"]
