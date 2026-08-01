from dataclasses import replace

import pytest

from agents.orchestrator.planner import DynamicPlanner, PlanCompiler, PlanRejected, descriptor_hash
from libs.integrations.catalog import ConnectionCapabilitySnapshot, TrustedCapabilityDefinition
from libs.integrations.catalog import slack_definitions


def _definition(
    capability_id, provider, effect="read", input_schema=None,
    output_schema=None,
):
    return TrustedCapabilityDefinition(
        capability_id=capability_id, version="1.0.0", provider=provider,
        input_schema=input_schema or {"type": "object", "additionalProperties": True},
        output_schema=output_schema or {"type": "object", "additionalProperties": True},
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


def _compiler_for(definitions):
    snapshots = [ConnectionCapabilitySnapshot(
        connection_id="conn:s", tenant_id="org:acme",
        capability_id=item.capability_id,
        capability_version=item.version, credential_version=1,
        effective_scopes=item.required_scopes, health="healthy",
        rollout_version="rollout-1",
    ) for item in definitions]
    return PlanCompiler(definitions, snapshots, "rollout-1")


def _reference_definitions():
    source = _definition(
        "slack.message.lookup", "slack",
        output_schema={
            "type": "object",
            "required": ["message_ts", "messages"],
            "properties": {
                "message_ts": {"type": "string"},
                "messages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["text"],
                        "properties": {"text": {"type": "string"}},
                        "additionalProperties": False,
                    },
                },
            },
            "additionalProperties": False,
        },
    )
    destination = _definition(
        "slack.thread.reply", "slack", "write",
        input_schema={
            "type": "object",
            "required": ["thread_ts"],
            "properties": {"thread_ts": {"type": "string"}},
            "anyOf": [{"required": ["thread_ts"]}],
            "additionalProperties": False,
        },
    )
    return source, destination


def _reference_plan(source, destination, reference, dependencies=("lookup",)):
    lookup = _step(source, "lookup", "conn:s", [])
    reply = _step(destination, "reply", "conn:s", list(dependencies))
    reply["input"] = {"thread_ts": {"$ref": reference}}
    return {
        "tenant_id": "org:acme", "goal": "reply to the found message",
        "steps": [lookup, reply],
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


def test_compiler_accepts_typed_reference_from_declared_ancestor_output():
    source, destination = _reference_definitions()

    result = _compiler_for([source, destination]).compile(_reference_plan(
        source, destination, "lookup.output.message_ts",
    ))

    assert result["steps"][1]["input"]["thread_ts"] == {
        "$ref": "lookup.output.message_ts"
    }


def test_compiler_rejects_reference_to_undeclared_output_path():
    source, destination = _reference_definitions()

    with pytest.raises(PlanRejected, match="undeclared source output path"):
        _compiler_for([source, destination]).compile(_reference_plan(
            source, destination, "lookup.output.missing_ts",
        ))


def test_compiler_rejects_incompatible_reference_type():
    source, destination = _reference_definitions()

    with pytest.raises(PlanRejected, match="incompatible reference type"):
        _compiler_for([source, destination]).compile(_reference_plan(
            source, destination, "lookup.output.messages",
        ))


def test_compiler_rejects_reference_to_undeclared_destination_input_path():
    source, destination = _reference_definitions()
    destination = replace(destination, input_schema={
        "type": "object", "additionalProperties": True,
    })

    with pytest.raises(PlanRejected, match="undeclared destination input path"):
        _compiler_for([source, destination]).compile(_reference_plan(
            source, destination, "lookup.output.message_ts",
        ))


def test_compiler_rejects_reference_to_future_step():
    source, destination = _reference_definitions()
    plan = _reference_plan(
        source, destination, "future.output.message_ts", dependencies=(),
    )
    plan["steps"][0]["step_id"] = "future"
    plan["steps"][0]["depends_on"] = ["reply"]

    with pytest.raises(PlanRejected, match="output reference is invalid"):
        _compiler_for([source, destination]).compile(plan)


def test_compiler_rejects_reference_to_unrelated_branch():
    source, destination = _reference_definitions()

    with pytest.raises(PlanRejected, match="output reference is invalid"):
        _compiler_for([source, destination]).compile(_reference_plan(
            source, destination, "lookup.output.message_ts", dependencies=(),
        ))


def test_compiler_rejects_reference_plan_after_catalog_descriptor_drift():
    source, destination = _reference_definitions()
    drifted = replace(source, output_schema={
        "type": "object",
        "properties": {"replacement_ts": {"type": "string"}},
        "additionalProperties": False,
    })

    with pytest.raises(PlanRejected, match="descriptor snapshot is stale"):
        _compiler_for([drifted, destination]).compile(_reference_plan(
            source, destination, "lookup.output.message_ts",
        ))


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


def test_model_cannot_invent_slack_entity_id_outside_resolver_projection():
    definition = _definition("slack.conversation.read", "slack")
    compiler = PlanCompiler([definition], [ConnectionCapabilitySnapshot(
        connection_id="conn:s", tenant_id="org:acme",
        capability_id=definition.capability_id,
        capability_version=definition.version, credential_version=1,
        effective_scopes=definition.required_scopes, health="healthy",
        rollout_version="rollout-1",
    )], "rollout-1")

    class InventingModel:
        def generate_plan(self, goal, capabilities, context):
            return {"tenant_id": "org:acme", "goal": goal, "steps": [{
                "step_id": "read", "capability_id": definition.capability_id,
                "capability_version": definition.version,
                "connection_id": "conn:s",
                "descriptor_snapshot_hash": descriptor_hash(definition),
                "input": {"channel_id": "C-INVENTED"}, "depends_on": [],
            }]}

    with pytest.raises(PlanRejected, match="deterministically resolved"):
        DynamicPlanner(InventingModel(), compiler).plan("read", {
            "slack_resolution": {"active_channel": {"id": "C-TRUSTED"}}
        })


@pytest.mark.parametrize(("goal", "capability_id", "resolution", "expected"), [
    ("Read #general", "slack.conversation.read",
     {"active_channel": {"id": "C1"}}, {"channel_id": "C1"}),
    ("Post in #general: hello", "slack.message.send",
     {"active_channel": {"id": "C1"}}, {"channel_id": "C1", "text": "hello"}),
    ("Reply there that I agree", "slack.thread.reply",
     {"active_channel": {"id": "C1"}, "active_thread": {"thread_ts": "1.0"}},
     {"channel_id": "C1", "thread_ts": "1.0", "text": "I agree"}),
    ("Send a direct message to Maria saying hello", "slack.direct_message.send",
     {"active_person": {"id": "U1"}}, {"user_id": "U1", "text": "hello"}),
])
def test_offline_slack_subset_compiles_only_resolved_exact_inputs(
    goal, capability_id, resolution, expected
):
    definition = next(item for item in slack_definitions()
                      if item.capability_id == capability_id)
    compiler = PlanCompiler([definition], [ConnectionCapabilitySnapshot(
        connection_id="conn:s", tenant_id="org:acme",
        capability_id=definition.capability_id,
        capability_version=definition.version, credential_version=1,
        effective_scopes=definition.required_scopes, health="healthy",
        rollout_version="rollout-1",
    )], "rollout-1")
    resolution = {**resolution, "active_connection": {"id": "conn:s"}}
    result = DynamicPlanner(object(), compiler).plan(goal, {
        "tenant_id": "org:acme", "slack_resolution": resolution,
    })
    assert result["steps"][0]["input"] == expected
