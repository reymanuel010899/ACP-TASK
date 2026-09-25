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
    TrustedCapabilityDefinition,
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
    assert first["version"] == "policy-v3"
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
    """Build a dispatch acting as a person, for a capability that needs one."""
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
    definition = _definition("slack.search.messages")
    binding, live = _personal(definition)

    decision = PolicyEvaluator(slack_definitions(), ROLLOUT).evaluate(
        binding, live, NOW,
    )

    assert decision["allowed"] is True
    assert decision["reason"] == "allowed"


def test_a_delegated_user_token_is_also_accepted():
    definition = _definition("slack.search.messages")
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
    definition = _definition("slack.search.messages")
    binding, live = _personal(definition, **overrides)

    decision = PolicyEvaluator(slack_definitions(), ROLLOUT).evaluate(
        binding, live, NOW,
    )

    assert decision["allowed"] is False
    assert decision["reason"] == reason


def test_enterprise_authority_is_refused_at_the_boundary():
    definition = _definition("slack.search.messages")
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
    definition = _definition("slack.search.messages")
    binding, live = _personal(definition)
    evaluator = PolicyEvaluator(slack_definitions(), ROLLOUT)

    original = evaluator.evaluate(binding, live, NOW)
    swapped = evaluator.evaluate(
        dict(binding, slack_subject_id="U-someone-else"), live, NOW,
    )

    # Swapping whose token it acts as must change the decision, or an approval
    # for one person would authorise a dispatch as another.
    assert original["input_hash"] != swapped["input_hash"]


def test_a_bot_capability_cannot_be_run_as_a_person():
    definition = _definition("slack.channels.list")
    binding, live = _personal(definition)

    decision = PolicyEvaluator(slack_definitions(), ROLLOUT).evaluate(
        binding, live, NOW,
    )

    # Listing channels is the installation's job. Running it as a person
    # would answer a differently-scoped question than the descriptor promises.
    assert decision["allowed"] is False
    assert decision["reason"] == "authority_profile_not_permitted"


def test_a_personal_capability_cannot_be_run_as_the_bot():
    definition = _definition("slack.search.messages")
    binding, _payload = _binding(definition)
    live = _connection(definition)

    decision = PolicyEvaluator(slack_definitions(), ROLLOUT).evaluate(
        binding, live, NOW,
    )

    assert decision["allowed"] is False
    assert decision["reason"] == "authority_profile_not_permitted"


# --- Account authority: a provider with no consent and no OAuth scopes ------
#
# The account holds two senders. Everything below is about proving that a
# lawful narrowing of one of them stops exactly the effects bound to it, and
# that nothing else about the connection has to move for that to happen.

ACCOUNT_ID = "AC0000000000000000000000000000001"
SENDER_A = "+18095550100"
SENDER_B = "+18095550200"
ACCOUNT_SCOPES = [
    "twilio:geo:DO",
    "twilio:geo:ES",
    "twilio:sender:%s" % SENDER_A,
    "twilio:sender:%s" % SENDER_B,
    "twilio:sms:send",
]


def _account_definition():
    return TrustedCapabilityDefinition(
        capability_id="twilio.sms.send",
        version="1.0.0",
        provider="twilio",
        input_schema={
            "type": "object",
            "required": ["to", "body", "from"],
            "properties": {
                "to": {"type": "string"},
                "body": {"type": "string"},
                "from": {"type": "string"},
            },
            "additionalProperties": False,
        },
        output_schema={"type": "object", "additionalProperties": True},
        # The capability names the family only. Which sender and which
        # destination this effect uses is per effect, so it travels in the
        # binding instead.
        required_scopes=frozenset({"twilio:sms:send"}),
        effect="write",
        risk="high",
        retry_policy="reconcile",
        preview_fields=("to", "body", "from"),
        verifier="twilio.message",
        authority_profile="account",
    )


def _account_binding(sender=SENDER_A, scopes=None, geo="ES"):
    definition = _account_definition()
    scopes = list(ACCOUNT_SCOPES if scopes is None else scopes)
    payload = {"to": "+34600000000", "body": "hello", "from": sender}
    payload_hash = canonical_payload_hash(payload)
    binding = {
        "user_principal_id": "user:alice",
        "agent_principal_id": "agent:orchestrator",
        "task_id": "revision:1:step:1",
        "tenant_id": "org:acme",
        "connection_id": "conn:twilio",
        "authority_profile": "account",
        "provider_account_id": ACCOUNT_ID,
        "credential_id": "credential:twilio",
        "credential_version": 3,
        "capability_id": definition.capability_id,
        "capability_version": definition.version,
        "descriptor_snapshot_hash": descriptor_hash(definition),
        "effect": "write",
        "bound_scopes": [
            "twilio:sender:%s" % sender, "twilio:geo:%s" % geo,
        ],
        "plan_graph_hash": "graph:1",
        "workflow_revision_id": "revision:1",
        "step_id": "step:1",
        "attempt": 1,
        "approval_payload_hash": payload_hash,
        "approval_expires_at": NOW + 300,
        "payload_hash": payload_hash,
        "slack_connect": False,
        "data_egress": False,
        "connection_snapshot": {
            "connection_id": "conn:twilio",
            "tenant_id": "org:acme",
            "capability_id": definition.capability_id,
            "capability_version": definition.version,
            "credential_version": 3,
            "effective_scopes": scopes,
            "health": "healthy",
            "rollout_version": ROLLOUT,
            "authority_profile": "account",
            "provider_account_id": ACCOUNT_ID,
        },
    }
    live = {
        "connection_id": "conn:twilio",
        "tenant_id": "org:acme",
        "status": "connected",
        "credential_id": "credential:twilio",
        "credential_version": 3,
        "granted_scopes": scopes,
        "enabled_capabilities": [definition.capability_id],
        "authority_profile": "account",
        "provider_account_id": ACCOUNT_ID,
        "account_status": "verified",
    }
    return definition, binding, live


def _account_evaluator(definition):
    return PolicyEvaluator((definition,), ROLLOUT)


def test_an_account_credential_carries_derived_authority_with_no_consent():
    definition, binding, live = _account_binding()

    decision = _account_evaluator(definition).evaluate(binding, live, NOW)

    assert decision["allowed"] is True
    assert decision["reason"] == "allowed"
    assert decision["version"] == "policy-v3"


def test_disabling_a_sender_fails_its_effects_closed_at_dispatch():
    definition, binding, _live = _account_binding()
    # Exactly what a sender disable does: one synthetic scope stops being
    # derived. Nothing else on the connection moves, and in particular the
    # credential version does not.
    narrowed = [
        scope for scope in ACCOUNT_SCOPES
        if scope != "twilio:sender:%s" % SENDER_A
    ]
    _definition_b, _binding_b, live = _account_binding(scopes=narrowed)
    binding["connection_snapshot"]["effective_scopes"] = narrowed

    decision = _account_evaluator(definition).evaluate(binding, live, NOW)

    assert decision["allowed"] is False
    assert decision["reason"] == "missing_bound_authority"


def test_disabling_one_sender_leaves_the_other_sender_dispatchable():
    narrowed = [
        scope for scope in ACCOUNT_SCOPES
        if scope not in ("twilio:sender:%s" % SENDER_A, "twilio:geo:ES")
    ]
    definition, binding, live = _account_binding(
        sender=SENDER_B, scopes=narrowed, geo="DO",
    )

    decision = _account_evaluator(definition).evaluate(binding, live, NOW)

    # The connection is the same, the credential is the same, the family is
    # the same. Only the disabled sender's effects stop.
    assert decision["allowed"] is True
    assert decision["reason"] == "allowed"


def test_a_paid_effect_must_say_which_verified_sender_it_leaves_from():
    definition, binding, live = _account_binding()
    binding["bound_scopes"] = []

    decision = _account_evaluator(definition).evaluate(binding, live, NOW)

    assert decision["allowed"] is False
    assert decision["reason"] == "bound_authority_missing"


def test_the_bound_sender_is_covered_by_the_policy_hash():
    definition, binding, live = _account_binding()
    evaluator = _account_evaluator(definition)

    original = evaluator.evaluate(binding, live, NOW)
    swapped = evaluator.evaluate(
        dict(binding, bound_scopes=["twilio:sender:%s" % SENDER_B]), live, NOW,
    )

    assert original["input_hash"] != swapped["input_hash"]


@pytest.mark.parametrize("mutation, reason", [
    (
        lambda binding, live: binding.update(provider_account_id=None),
        "account_authority_unbound",
    ),
    (
        lambda binding, live: live.update(provider_account_id="AC-other"),
        "account_authority_mismatch",
    ),
    (
        lambda binding, live: binding["connection_snapshot"].update(
            provider_account_id="AC-other"
        ),
        "account_authority_mismatch",
    ),
    (
        lambda binding, live: live.update(account_status="suspended"),
        "account_authority_unverified",
    ),
    (
        lambda binding, live: live.update(account_status="unavailable"),
        "account_authority_unverified",
    ),
])
def test_account_authority_fails_closed_on_identity_and_verification_drift(
    mutation, reason,
):
    definition, binding, live = _account_binding()
    mutation(binding, live)

    decision = _account_evaluator(definition).evaluate(binding, live, NOW)

    assert decision["allowed"] is False
    assert decision["reason"] == reason


@pytest.mark.parametrize("mutation", [
    lambda binding, live: live.update(credential_version=4),
    lambda binding, live: binding["connection_snapshot"].update(
        credential_version=4
    ),
    lambda binding, live: binding.update(credential_version=4),
    lambda binding, live: binding.update(credential_version=0),
])
def test_a_static_credential_version_must_agree_everywhere(mutation):
    definition, binding, live = _account_binding()
    mutation(binding, live)

    decision = _account_evaluator(definition).evaluate(binding, live, NOW)

    # Credential version means one thing for a manually rotated static
    # credential: which custody generation of the sealed secret this binding
    # was made against. Disagreement anywhere means the secret moved under a
    # binding that predates it.
    assert decision["allowed"] is False
    assert decision["reason"] == "credential_mismatch"


def test_an_account_capability_cannot_be_run_as_the_bot():
    definition, binding, live = _account_binding()
    for target in (binding, live, binding["connection_snapshot"]):
        target["authority_profile"] = "bot"

    decision = _account_evaluator(definition).evaluate(binding, live, NOW)

    assert decision["allowed"] is False
    assert decision["reason"] == "authority_profile_not_permitted"
