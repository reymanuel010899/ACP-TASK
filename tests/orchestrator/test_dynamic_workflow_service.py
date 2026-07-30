from agents.orchestrator.dynamic_workflow_service import DynamicWorkflowService
from agents.orchestrator.planner import descriptor_hash
from agents.orchestrator.workflow_repository import WorkflowRepository
from libs.integrations.catalog import TrustedCapabilityDefinition


def test_service_uses_connected_catalog_and_persists_approval_ready_revision(tmp_path):
    definition = TrustedCapabilityDefinition(
        capability_id="synthetic.read", version="1", provider="synthetic",
        input_schema={"type": "object"}, output_schema={"type": "object"},
        required_scopes=frozenset({"read"}), effect="read", risk="low",
        retry_policy="safe", preview_fields=(), verifier=None,
    )
    class Connections:
        def list_installations(self, tenant, principal):
            return [{"connection_id": "conn:1", "status": "connected", "credential_version": 1,
                     "granted_scopes": ["read"], "enabled_capabilities": ["synthetic.read"]}]
    class Brain:
        def generate_plan(self, goal, capabilities, context):
            assert capabilities[0]["connections"] == ["conn:1"]
            return {"tenant_id": context["tenant_id"], "goal": goal, "steps": [{
                "step_id": "read", "capability_id": "synthetic.read", "capability_version": "1",
                "connection_id": "conn:1", "descriptor_snapshot_hash": descriptor_hash(definition),
                "input": {}, "depends_on": [],
            }]}
    service = DynamicWorkflowService(Brain(), [definition], Connections(), WorkflowRepository(str(tmp_path / "w.db")), rollout_version="r1")
    result = service.plan("org:1", "user:1", "read it")
    assert result["revision"]["steps"][0]["capability_id"] == "synthetic.read"
    assert result["plan"]["shadow_mode"] is True
