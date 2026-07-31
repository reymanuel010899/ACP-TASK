import pytest

from agents.orchestrator.conversation_state import ConciergeConversationStore
from agents.orchestrator.dynamic_workflow_service import DynamicWorkflowService
from agents.orchestrator.workflow_repository import WorkflowRepository
from libs.integrations.catalog import slack_definitions


class _TenantConnections:
    def list_tenant_installations(self, tenant_id, provider):
        assert provider == "slack"
        if tenant_id != "org:acme":
            return []
        return [{
            "connection_id": "conn:acme", "team_name": "Acme",
            "status": "connected", "credential_version": 1,
            "granted_scopes": ["channels:read", "chat:write"],
            "enabled_capabilities": ["slack.channels.list", "slack.message.send"],
        }]


def test_tenant_member_can_resolve_own_installation_but_other_tenant_cannot_discover_it(tmp_path):
    workflows = WorkflowRepository(str(tmp_path / "workflows.db"))
    store = ConciergeConversationStore(workflows, clock=lambda: 10)
    service = DynamicWorkflowService(
        object(), slack_definitions(), _TenantConnections(), workflows,
        conversation_store=store, clock=lambda: 10,
    )

    own = service.coordinate_slack_turn(
        "org:acme", "user:member", "Read #general",
        channels=[{"id": "C1", "name": "general"}],
    )
    foreign = service.coordinate_slack_turn(
        "org:other", "user:member", "Read #general",
        channels=[{"id": "C1", "name": "general"}],
    )

    assert own["resolved"]["active_connection"] == {"id": "conn:acme", "label": "Acme"}
    assert foreign["state"] == "needs_input"
    assert foreign["need"]["field"] == "workspace"
    assert foreign["need"]["options"] == []

    with pytest.raises(KeyError, match="conversation unavailable"):
        service.materialize_slack_write(
            own["conversation_id"], "org:other", "user:member",
            "slack.message.send", "No autorizado",
        )
