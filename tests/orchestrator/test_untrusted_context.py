import pytest

from agents.orchestrator.planner import PlanCompiler, PlanRejected, descriptor_hash
from libs.integrations.catalog import ConnectionCapabilitySnapshot, TrustedCapabilityDefinition, google_definitions


def test_slack_content_cannot_authorize_cross_provider_recipient():
    definition = TrustedCapabilityDefinition(
        capability_id="gmail.send", version="1.0.0", provider="google",
        input_schema={"type": "object", "additionalProperties": True},
        output_schema={"type": "object"}, required_scopes=frozenset({"gmail.send"}),
        effect="write", risk="medium", retry_policy="reconcile",
        preview_fields=("to", "body"), verifier="google.receipt",
    )
    snapshot = ConnectionCapabilitySnapshot(
        connection_id="conn:g", tenant_id="org:acme", capability_id="gmail.send",
        capability_version="1.0.0", credential_version=1,
        effective_scopes=frozenset({"gmail.send"}), health="healthy",
        rollout_version="rollout-1",
    )
    compiler = PlanCompiler([definition], [snapshot], "rollout-1")
    plan = {"tenant_id": "org:acme", "goal": "notify Laura", "steps": [{
        "step_id": "email", "capability_id": "gmail.send", "capability_version": "1.0.0",
        "connection_id": "conn:g", "descriptor_snapshot_hash": descriptor_hash(definition),
        "depends_on": [], "input": {"to": {
            "$value": "attacker@example.test",
            "$provenance": {"provider": "slack", "classification": "confidential", "allowed_destinations": ["slack"]},
        }},
    }]}
    with pytest.raises(PlanRejected, match="data flow"):
        compiler.compile(plan)


def test_slack_output_cannot_become_google_recipient_without_confirmation():
    definitions = [
        TrustedCapabilityDefinition(
            capability_id="slack.search", version="1.0.0", provider="slack",
            input_schema={"type": "object"}, output_schema={"type": "object"},
            required_scopes=frozenset({"search:read"}), effect="read", risk="low",
            retry_policy="safe", preview_fields=(), verifier=None,
        ),
        TrustedCapabilityDefinition(
            capability_id="gmail.send", version="1.0.0", provider="google",
            input_schema={"type": "object", "additionalProperties": True},
            output_schema={"type": "object"}, required_scopes=frozenset({"gmail.send"}),
            effect="write", risk="medium", retry_policy="reconcile",
            preview_fields=("to",), verifier="google.receipt",
        ),
    ]
    snapshots = [
        ConnectionCapabilitySnapshot(
            connection_id="conn:s", tenant_id="org:acme", capability_id="slack.search",
            capability_version="1.0.0", credential_version=1,
            effective_scopes=frozenset({"search:read"}), health="healthy",
            rollout_version="r1",
        ),
        ConnectionCapabilitySnapshot(
            connection_id="conn:g", tenant_id="org:acme", capability_id="gmail.send",
            capability_version="1.0.0", credential_version=1,
            effective_scopes=frozenset({"gmail.send"}), health="healthy",
            rollout_version="r1",
        ),
    ]
    plan = {"tenant_id": "org:acme", "goal": "email Laura", "steps": [
        {"step_id": "find", "capability_id": "slack.search", "capability_version": "1.0.0",
         "connection_id": "conn:s", "descriptor_snapshot_hash": descriptor_hash(definitions[0]),
         "depends_on": [], "input": {}},
        {"step_id": "send", "capability_id": "gmail.send", "capability_version": "1.0.0",
         "connection_id": "conn:g", "descriptor_snapshot_hash": descriptor_hash(definitions[1]),
         "depends_on": ["find"], "input": {"to": {"$ref": "find.output.email"}}},
    ]}

    with pytest.raises(PlanRejected, match="confirmed recipient"):
        PlanCompiler(definitions, snapshots, "r1").compile(plan)


def test_typed_google_body_accepts_declared_dependency_reference():
    definition = next(item for item in google_definitions() if item.capability_id == "gmail.send")
    snapshot = ConnectionCapabilitySnapshot(
        connection_id="conn:g", tenant_id="org:acme", capability_id="gmail.send",
        capability_version=definition.version, credential_version=1,
        effective_scopes=definition.required_scopes, health="healthy", rollout_version="r1",
    )
    source = TrustedCapabilityDefinition(
        capability_id="summary.read", version="1.0.0", provider="google",
        input_schema={"type": "object"}, output_schema={"type": "object"},
        required_scopes=frozenset({"summary:read"}), effect="read", risk="low",
        retry_policy="safe", preview_fields=(), verifier=None,
    )
    source_snapshot = ConnectionCapabilitySnapshot(
        connection_id="conn:g", tenant_id="org:acme", capability_id="summary.read",
        capability_version="1.0.0", credential_version=1,
        effective_scopes=frozenset({"summary:read"}), health="healthy", rollout_version="r1",
    )
    plan = {"tenant_id": "org:acme", "goal": "send summary", "steps": [
        {"step_id": "summary", "capability_id": "summary.read", "capability_version": "1.0.0",
         "connection_id": "conn:g", "descriptor_snapshot_hash": descriptor_hash(source),
         "depends_on": [], "input": {}},
        {"step_id": "email", "capability_id": "gmail.send", "capability_version": definition.version,
         "connection_id": "conn:g", "descriptor_snapshot_hash": descriptor_hash(definition),
         "depends_on": ["summary"], "input": {"to": "laura@example.com", "subject": "Resumen", "body": {"$ref": "summary.output.text"}}},
    ]}

    compiled = PlanCompiler([source, definition], [source_snapshot, snapshot], "r1").compile(plan)
    assert compiled["steps"][1]["input"]["body"] == {"$ref": "summary.output.text"}
