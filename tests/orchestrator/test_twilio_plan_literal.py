import pytest

from agents.orchestrator.planner import PlanCompiler, PlanRejected, descriptor_hash
from libs.integrations.catalog import ConnectionCapabilitySnapshot, twilio_definitions


def test_twilio_preview_destination_may_never_be_a_reference():
    definition = next(item for item in twilio_definitions() if item.capability_id == "twilio.sms.send")
    snapshot = ConnectionCapabilitySnapshot(
        connection_id="conn:twilio", tenant_id="tenant:a",
        capability_id=definition.capability_id,
        capability_version=definition.version, credential_version=1,
        effective_scopes=definition.required_scopes, health="healthy",
        rollout_version="production-v1",
    )
    compiler = PlanCompiler((definition,), (snapshot,), "production-v1")
    plan = {
        "tenant_id": "tenant:a", "goal": "send", "blockers": [],
        "steps": [{
            "step_id": "send", "capability_id": definition.capability_id,
            "capability_version": definition.version,
            "connection_id": "conn:twilio",
            "descriptor_snapshot_hash": descriptor_hash(definition),
            "input": {
                "contact_id": "contact:1", "contact_version": "v1",
                "address_id": "address:1", "to": {"$ref": "resolve.output.to"},
                "from": "+18095550100", "body": "Hola",
                "status_callback": "https://example.test/cb",
                "purpose": "transactional",
            }, "depends_on": ["resolve"],
        }],
    }
    with pytest.raises(PlanRejected, match="preview fields must be literal"):
        compiler.compile(plan)
