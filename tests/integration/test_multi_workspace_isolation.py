import pytest

from agents.orchestrator.planner import PlanCompiler, PlanRejected, descriptor_hash
from libs.integrations.catalog import ConnectionCapabilitySnapshot, slack_definitions


def test_connection_snapshot_cannot_cross_tenant_or_workspace():
    definition = next(item for item in slack_definitions() if item.capability_id == "slack.message.send")
    snapshots = [
        ConnectionCapabilitySnapshot("conn:acme", "org:acme", definition.capability_id, definition.version, 1, definition.required_scopes, "healthy", "r1"),
        ConnectionCapabilitySnapshot("conn:other", "org:other", definition.capability_id, definition.version, 1, definition.required_scopes, "healthy", "r1"),
    ]
    plan = {"tenant_id": "org:acme", "goal": "post", "steps": [{"step_id": "send", "capability_id": definition.capability_id, "capability_version": definition.version, "connection_id": "conn:other", "descriptor_snapshot_hash": descriptor_hash(definition), "depends_on": [], "input": {"channel_id": "C1", "text": "hello"}}]}
    with pytest.raises(PlanRejected, match="tenant"):
        PlanCompiler([definition], snapshots, "r1").compile(plan)
