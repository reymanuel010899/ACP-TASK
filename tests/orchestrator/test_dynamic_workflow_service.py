from agents.orchestrator.dynamic_workflow_service import DynamicWorkflowService
from agents.orchestrator.conversation_state import ConciergeConversationStore
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
    assert result["revision"]["status"] == "authorized"


def test_service_persists_one_slack_need_and_rejects_expired_pronoun(tmp_path):
    class Connections:
        def list_tenant_installations(self, tenant, provider):
            return [{"connection_id": "conn:s", "team_name": "Acme", "status": "connected"}]

    now = [100]
    repository = WorkflowRepository(str(tmp_path / "w.db"))
    store = ConciergeConversationStore(repository, clock=lambda: now[0], ttl_seconds=180)
    service = DynamicWorkflowService(
        object(), [], Connections(), repository, clock=lambda: now[0],
        conversation_store=store,
    )
    result = service.coordinate_slack_turn(
        "org:1", "user:1", "Manda un mensaje en #nuevo-canal",
        conversation_id="conversation:1",
        channels=[{"id": "C1", "name": "nuevo-canal"}],
    )
    assert result["need"]["field"] == "message_text"
    persisted = store.get("conversation:1", "org:1", "user:1")
    assert persisted["active_channel"]["id"] == "C1"
    assert persisted["blocking_need"]["field"] == "message_text"

    now[0] = 281
    expired = service.coordinate_slack_turn(
        "org:1", "user:1", "Respóndele ahí que sí",
        conversation_id="conversation:1",
    )
    assert expired["state"] == "expired"
    assert "active_channel" not in expired


def test_completed_read_presentation_is_generated_once_across_polls(tmp_path):
    class Connections:
        def list_installations(self, tenant, principal):
            return []
    repository = WorkflowRepository(str(tmp_path / "w.db"))
    store = ConciergeConversationStore(repository, clock=lambda: 100)
    store.create("org:1", "user:1", "conversation:1")
    service = DynamicWorkflowService(
        object(), [], Connections(), repository, conversation_store=store,
    )
    class Presenter:
        def __init__(self): self.calls = 0
        def present(self, question, evidence, locale):
            self.calls += 1
            return {"locale": locale, "answer": "grounded", "citations": [],
                    "partial": False}
    presenter = Presenter()
    first = service.present_read_once(
        "conversation:1", "org:1", "user:1", presenter,
        "question", {"messages": []}, "en",
    )
    second = service.present_read_once(
        "conversation:1", "org:1", "user:1", presenter,
        "question", {"messages": [{"text": "changed"}]}, "en",
    )
    assert first == second
    assert presenter.calls == 1
