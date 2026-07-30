from agents.orchestrator.planner import DynamicPlanner, PlanCompiler, descriptor_hash
from libs.integrations.catalog import ConnectionCapabilitySnapshot, TrustedCapabilityDefinition


def _definition(capability_id, provider, effect="read"):
    return TrustedCapabilityDefinition(
        capability_id=capability_id, version="1.0.0", provider=provider,
        input_schema={"type": "object", "additionalProperties": True},
        output_schema={"type": "object", "additionalProperties": True},
        required_scopes=frozenset({"scope:%s" % capability_id}), effect=effect,
        risk="medium" if effect == "write" else "low", retry_policy="safe",
        preview_fields=("payload",) if effect == "write" else (), verifier=None,
    )


class Model:
    def generate_plan(self, goal, capabilities, context):
        ids = [item["capability_id"] for item in capabilities]
        assert ids == ["calendar.create", "gmail.send", "slack.thread.read", "slack.thread.reply"]
        assert capabilities[0]["connections"] == ["conn:g"]
        assert capabilities[0]["descriptor_snapshot_hash"]
        return {"tenant_id": "org:acme", "goal": goal, "steps": [
            _step(context["definitions"]["slack.thread.read"], "read", "conn:s", []),
            _step(context["definitions"]["calendar.create"], "calendar", "conn:g", ["read"]),
            _step(context["definitions"]["gmail.send"], "email", "conn:g", ["calendar"]),
            _step(context["definitions"]["slack.thread.reply"], "reply", "conn:s", ["email"]),
        ]}


def _step(definition, step_id, connection_id, dependencies):
    return {
        "step_id": step_id, "capability_id": definition.capability_id,
        "capability_version": definition.version, "connection_id": connection_id,
        "descriptor_snapshot_hash": descriptor_hash(definition),
        "input": {}, "depends_on": dependencies,
    }


def test_same_dynamic_contract_composes_slack_calendar_gmail_without_named_workflow():
    definitions = [
        _definition("slack.thread.read", "slack"),
        _definition("calendar.create", "google", "write"),
        _definition("gmail.send", "google", "write"),
        _definition("slack.thread.reply", "slack", "write"),
    ]
    snapshots = [ConnectionCapabilitySnapshot(
        connection_id="conn:s" if item.provider == "slack" else "conn:g",
        tenant_id="org:acme", capability_id=item.capability_id,
        capability_version=item.version, credential_version=1,
        effective_scopes=item.required_scopes, health="healthy",
        rollout_version="rollout-1",
    ) for item in definitions]
    compiler = PlanCompiler(definitions, snapshots, "rollout-1")
    planner = DynamicPlanner(Model(), compiler, shadow_mode=True)

    result = planner.plan("Schedule the agreed interview and notify the thread", {
        "definitions": {item.capability_id: item for item in definitions}
    })

    assert [step["capability_id"] for step in result["steps"]] == [
        "slack.thread.read", "calendar.create", "gmail.send", "slack.thread.reply"
    ]
    assert result["shadow_mode"] is True
    assert "schedule_from_slack" not in str(result)


def test_offline_planner_can_list_public_slack_channels():
    definition = _definition("slack.channels.list", "slack")
    compiler = PlanCompiler([definition], [ConnectionCapabilitySnapshot(
        connection_id="conn:s", tenant_id="org:acme",
        capability_id=definition.capability_id,
        capability_version=definition.version, credential_version=1,
        effective_scopes=definition.required_scopes, health="healthy",
        rollout_version="rollout-1",
    )], "rollout-1")

    result = DynamicPlanner(object(), compiler, shadow_mode=False).plan(
        "Lista los canales públicos de Slack",
        {"tenant_id": "org:acme"},
    )

    assert result["steps"] == [{
        "step_id": "slack-public-channels",
        "capability_id": "slack.channels.list",
        "capability_version": "1.0.0",
        "connection_id": "conn:s",
        "descriptor_snapshot_hash": descriptor_hash(definition),
        "credential_version": 1,
        "input": {},
        "depends_on": [],
        "effect": "read",
        "risk": "low",
        "retry_policy": "safe",
        "provider": "slack",
        "agent_offer_id": None,
    }]
    assert result["shadow_mode"] is False
