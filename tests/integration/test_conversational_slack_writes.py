from agents.orchestrator.action_repository import ActionRepository
from agents.orchestrator.conversation_state import ConciergeConversationStore
from agents.orchestrator.dynamic_workflow_service import DynamicWorkflowService
from agents.orchestrator.workflow_broker_dispatcher import WorkflowBrokerDispatcher
from agents.orchestrator.workflow_executor import WorkflowExecutor
from agents.orchestrator.workflow_repository import WorkflowRepository
from libs.integrations.catalog import slack_definitions


def test_missing_scope_retains_draft_and_safe_retry_dispatches_once(tmp_path):
    workflows = WorkflowRepository(str(tmp_path / "workflows.db"))
    actions = ActionRepository(str(tmp_path / "actions.db"))
    store = ConciergeConversationStore(workflows, clock=lambda: 10)
    store.create("org:1", "user:1", "conversation:1")
    store.update("conversation:1", "org:1", "user:1",
                 active_connection={"id": "conn:s", "label": "Acme"},
                 active_channel={"id": "C1", "name": "general"})

    class Connections:
        enabled = ["slack.message.send"]
        def _record(self):
            return {"connection_id": "conn:s", "team_name": "Acme", "team_id": "T1",
                    "status": "connected", "credential_id": "cred:1",
                    "credential_version": 1, "granted_scopes": ["chat:write"],
                    "enabled_capabilities": list(self.enabled)}
        def list_tenant_installations(self, tenant, provider): return [self._record()]
        def get_installation(self, connection_id, tenant): return self._record()
    connections = Connections()
    service = DynamicWorkflowService(
        object(), slack_definitions(), connections, workflows,
        conversation_store=store, clock=lambda: 10,
    )
    draft = service.materialize_slack_write(
        "conversation:1", "org:1", "user:1", "slack.message.send", "Hola"
    )
    service.approve_slack_draft(
        "conversation:1", "org:1", "user:1", draft["draft_hash"]
    )
    connections.enabled = []
    provider_calls = []
    class Broker:
        def execute(self, lease, binding, payload):
            provider_calls.append(payload)
            return 200, {"receipt": {"provider": "slack", "provider_id": "1.0",
                                      "channel_id": "C1", "message_ts": "1.0"},
                         "execution_attestation": {"attestation_id": "att:1"}}
    executor = WorkflowExecutor(
        workflows,
        WorkflowBrokerDispatcher(actions, Broker(), connections, workflows, clock=lambda: 11),
        clock=lambda: 11,
    )
    result = executor.run_until_blocked(
        draft["workflow_run_id"], draft["workflow_revision_id"], "org:1", "worker"
    )
    assert result["status"] == "retryable_failure"
    assert result["recovery"].startswith("missing_scope:")
    assert store.get("conversation:1", "org:1", "user:1")["pending_draft"]["text"] == "Hola"
    assert provider_calls == []
    failed_revision = workflows.get_revision(
        draft["workflow_run_id"], draft["workflow_revision_id"], "org:1"
    )
    assert workflows.recovery_options(failed_revision)["scopeUpgradeStepIds"] == ["slack-write"]

    connections.enabled = ["slack.message.send"]
    assert workflows.retry_corrected_write(
        draft["workflow_revision_id"], "slack-write", "org:1"
    )
    assert executor.run_until_blocked(
        draft["workflow_run_id"], draft["workflow_revision_id"], "org:1", "worker"
    )["status"] == "complete"
    assert provider_calls == [{"channel_id": "C1", "text": "Hola"}]
