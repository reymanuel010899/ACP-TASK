import json

from agents.orchestrator.action_repository import ActionRepository
from libs.connectors.slack import SlackActionExecutor
from libs.integrations.catalog import ProviderRuntime, ProviderRuntimeRegistry, slack_definitions
from services.action_broker.app import ActionBroker


NOW = 1_700_000_000


class Response:
    status_code = 200
    headers = {}

    def json(self):
        return {"ok": True, "channel": "C1", "ts": "123.45"}


class HTTP:
    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return Response()


class Vault:
    def use_managed_oauth(self, credential_id, identity, operation):
        return operation(json.dumps({
            "access_token": "xoxb-broker-only",
            "refresh_token": "xoxe-sealed",
            "granted_scopes": ["chat:write"],
        }).encode())


class Connector:
    pass


def test_slack_write_requires_live_snapshot_and_executes_through_native_runtime(tmp_path):
    actions = ActionRepository(str(tmp_path / "actions.sqlite3"))
    http = HTTP()
    executor = SlackActionExecutor(http=http)
    registry = ProviderRuntimeRegistry((ProviderRuntime(
        provider="slack",
        connector=Connector(),
        executor=executor,
        definitions=slack_definitions(),
    ),))
    broker = ActionBroker(
        actions, object(), Vault(), object(), clock=lambda: NOW,
        identity_verifier=lambda _url, _principal: True,
        agent_url_resolver=lambda _principal: "https://agent.test/a2a",
        credential_authorizer=lambda _binding: True,
        runtime_registry=registry,
        rollout_version="rollout-1",
    )
    payload = {"channel_id": "C1", "text": "Hello"}
    proposal = actions.create_proposal(
        "user:alice", "agent:helper", "cred:slack",
        "slack.message.send", payload, NOW + 300,
    )
    actions.decide(proposal["proposal_id"], 1, "user:alice", True, NOW)
    binding = {
        "proposal_id": proposal["proposal_id"], "version": 1,
        "user_principal_id": "user:alice", "agent_principal_id": "agent:helper",
        "task_id": "task-1", "credential_id": "cred:slack",
        "capability_id": "slack.message.send", "payload_hash": proposal["payload_hash"],
        "idempotency_key": proposal["idempotency_key"], "connection_id": "conn:1",
        "tenant_id": "org:acme", "team_id": "T1", "bot_user_id": "U-BOT",
        "connection_snapshot": {
            "connection_id": "conn:1", "tenant_id": "org:acme",
            "capability_id": "slack.message.send", "capability_version": "1.0.0",
            "credential_version": 1, "effective_scopes": ["chat:write"],
            "health": "healthy", "rollout_version": "rollout-1",
        },
    }
    lease = actions.issue_lease(
        "user:alice", "agent:helper", "task-1", "cred:slack",
        ["slack.message.send"], NOW + 60,
    )

    status, result = broker.execute(lease, binding, payload)

    assert status == 200
    assert result["receipt"]["team_id"] == "T1"
    assert "xox" not in json.dumps(result)
    assert http.calls[0][2]["headers"]["Authorization"] == "Bearer xoxb-broker-only"
