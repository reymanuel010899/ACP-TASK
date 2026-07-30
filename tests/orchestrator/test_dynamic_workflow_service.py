import pytest

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


def test_changed_slack_draft_invalidates_prior_approval(tmp_path):
    from agents.orchestrator.conversation_state import ConciergeConversationStore
    from libs.integrations.catalog import slack_definitions
    class Connections:
        def list_tenant_installations(self, tenant, provider):
            return [{
                "connection_id": "conn:s", "team_name": "Acme", "status": "connected",
                "credential_version": 3, "granted_scopes": ["chat:write"],
                "enabled_capabilities": ["slack.message.send"],
            }]
    repository = WorkflowRepository(str(tmp_path / "w.db"))
    store = ConciergeConversationStore(repository, clock=lambda: 10)
    store.create("org:1", "user:1", "conversation:1")
    store.update("conversation:1", "org:1", "user:1",
                 active_connection={"id": "conn:s", "label": "Acme"},
                 active_channel={"id": "C1", "name": "general"})
    service = DynamicWorkflowService(
        object(), slack_definitions(), Connections(), repository,
        conversation_store=store, clock=lambda: 10,
    )
    first = service.materialize_slack_write(
        "conversation:1", "org:1", "user:1", "slack.message.send", "Hola"
    )
    service.approve_slack_draft(
        "conversation:1", "org:1", "user:1", first["draft_hash"]
    )
    second = service.materialize_slack_write(
        "conversation:1", "org:1", "user:1", "slack.message.send", "Hola equipo"
    )
    with pytest.raises(ValueError, match="draft binding changed"):
        service.approve_slack_draft(
            "conversation:1", "org:1", "user:1", first["draft_hash"]
        )
    assert not repository.is_revision_approved(
        second["workflow_run_id"], second["workflow_revision_id"],
        "org:1", second["plan_graph_hash"], 10,
    )
    store.update("conversation:1", "org:1", "user:1",
                 active_channel={"id": "C2", "name": "other"})
    with pytest.raises(ValueError, match="draft binding changed"):
        service.approve_slack_draft(
            "conversation:1", "org:1", "user:1", second["draft_hash"]
        )


def test_thread_and_dm_drafts_materialize_exact_targets_and_localized_success(tmp_path):
    from agents.orchestrator.conversation_state import ConciergeConversationStore
    from libs.integrations.catalog import slack_definitions
    class Connections:
        def list_tenant_installations(self, tenant, provider):
            return [{"connection_id": "conn:s", "team_name": "Acme", "status": "connected",
                     "credential_version": 1, "granted_scopes": ["chat:write", "im:write"],
                     "enabled_capabilities": ["slack.thread.reply", "slack.direct_message.send"]}]
    repository = WorkflowRepository(str(tmp_path / "w.db"))
    store = ConciergeConversationStore(repository, clock=lambda: 10)
    store.create("org:1", "user:1", "conversation:1")
    store.update("conversation:1", "org:1", "user:1",
                 active_connection={"id": "conn:s", "label": "Acme"},
                 active_channel={"id": "C1", "name": "general"},
                 active_thread={"channel_id": "C1", "thread_ts": "1.0"})
    service = DynamicWorkflowService(object(), slack_definitions(), Connections(), repository,
                                     conversation_store=store, clock=lambda: 10)
    reply = service.materialize_slack_write(
        "conversation:1", "org:1", "user:1", "slack.thread.reply", "De acuerdo"
    )
    step = repository.get_revision(reply["workflow_run_id"], reply["workflow_revision_id"], "org:1")["steps"][0]
    assert step["input"] == {"channel_id": "C1", "thread_ts": "1.0", "text": "De acuerdo"}

    store.update("conversation:1", "org:1", "user:1",
                 active_person={"id": "U1", "display_name": "María"})
    dm = service.materialize_slack_write(
        "conversation:1", "org:1", "user:1", "slack.direct_message.send", "Hola"
    )
    step = repository.get_revision(dm["workflow_run_id"], dm["workflow_revision_id"], "org:1")["steps"][0]
    assert step["input"] == {"user_id": "U1", "text": "Hola"}
    assert dm["destination_label"] == "María"
    assert service.complete_slack_write(
        "conversation:1", "org:1", "user:1", "es"
    )["answer"] == "Mensaje enviado"
    state = store.get("conversation:1", "org:1", "user:1")
    assert state.get("pending_draft") is None
    assert state["status"] == "succeeded"
