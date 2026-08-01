import json

import pytest

from agents.orchestrator.action_repository import ActionRepository
from libs.connectors.base import ProviderNetworkError
from libs.connectors.slack import SlackAPIError, SlackActionExecutor
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


class FailingExecutor:
    def __init__(self, error):
        self.error = error
        self.calls = 0

    def execute(self, *_args):
        self.calls += 1
        raise self.error


def _approved_slack_write(tmp_path, executor, rotator=None, payload=None):
    actions = ActionRepository(str(tmp_path / "actions.sqlite3"))
    definition = next(
        item for item in slack_definitions()
        if item.capability_id == "slack.message.send"
    )
    registry = ProviderRuntimeRegistry((ProviderRuntime(
        provider="slack", connector=Connector(), executor=executor,
        definitions=(definition,),
    ),))
    broker = ActionBroker(
        actions, object(), Vault(), object(), clock=lambda: NOW,
        identity_verifier=lambda _url, _principal: True,
        agent_url_resolver=lambda _principal: "https://agent.test/a2a",
        credential_authorizer=lambda _binding: True,
        runtime_registry=registry, rollout_version="rollout-1",
        credential_rotators={"slack": rotator} if rotator else None,
    )
    payload = payload or {"channel_id": "C1", "text": "Hello"}
    proposal = actions.create_proposal(
        "user:alice", "agent:helper", "cred:slack",
        definition.capability_id, payload, NOW + 300,
    )
    actions.decide(proposal["proposal_id"], 1, "user:alice", True, NOW)
    binding = {
        "proposal_id": proposal["proposal_id"], "version": 1,
        "user_principal_id": "user:alice", "agent_principal_id": "agent:helper",
        "task_id": "task-1", "credential_id": "cred:slack",
        "capability_id": definition.capability_id,
        "payload_hash": proposal["payload_hash"],
        "idempotency_key": proposal["idempotency_key"],
        "connection_id": "conn:1", "tenant_id": "org:acme",
        "team_id": "T1", "bot_user_id": "U-BOT",
        "connection_snapshot": {
            "connection_id": "conn:1", "tenant_id": "org:acme",
            "capability_id": definition.capability_id,
            "capability_version": definition.version,
            "credential_version": 1, "effective_scopes": ["chat:write"],
            "health": "healthy", "rollout_version": "rollout-1",
        },
    }
    lease = actions.issue_lease(
        "user:alice", "agent:helper", "task-1", "cred:slack",
        [definition.capability_id], NOW + 60,
    )
    return broker, actions, proposal, binding, lease, payload


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


@pytest.mark.parametrize(("error", "expected_status"), [
    (SlackAPIError("chat.postMessage", "missing_scope", "scope"), 403),
    (SlackAPIError("chat.postMessage", "not_in_channel", "membership"), 403),
    (SlackAPIError("chat.postMessage", "invalid_arguments", "validation"), 422),
    (SlackAPIError("chat.postMessage", "message_not_found", "provider"), 409),
], ids=lambda value: value.code if isinstance(value, SlackAPIError) else None)
def test_deterministic_slack_write_errors_never_become_unknown(
    tmp_path, error, expected_status,
):
    executor = FailingExecutor(error)
    broker, actions, proposal, binding, lease, payload = _approved_slack_write(
        tmp_path, executor,
    )

    status, body = broker.execute(lease, binding, payload)

    assert status == expected_status
    assert body["error"] == error.code
    assert body["category"] == error.category
    assert body["outcome_certainty"] == "safe"
    assert actions.get(proposal["proposal_id"])["status"] == "failed"
    assert executor.calls == 1


def test_network_failure_before_provider_dispatch_is_safe(tmp_path):
    class FailingRotator:
        def rotate(self, *_args):
            raise ProviderNetworkError("refresh transport unavailable")

    executor = FailingExecutor(AssertionError("executor must not be called"))
    broker, actions, proposal, binding, lease, payload = _approved_slack_write(
        tmp_path, executor, rotator=FailingRotator(),
    )

    status, body = broker.execute(lease, binding, payload)

    assert status != 202
    assert body["outcome_certainty"] == "safe"
    assert actions.get(proposal["proposal_id"])["status"] == "failed"
    assert executor.calls == 0


def test_network_failure_after_provider_dispatch_requires_reconciliation(tmp_path):
    executor = FailingExecutor(ProviderNetworkError("timeout after dispatch"))
    broker, actions, proposal, binding, lease, payload = _approved_slack_write(
        tmp_path, executor,
    )

    assert broker.execute(lease, binding, payload) == (
        202, {"status": "execution_unknown"},
    )
    assert actions.get(proposal["proposal_id"])["status"] == "execution_unknown"


def test_schema_rejection_stays_pre_dispatch_and_retryable_by_same_approval(tmp_path):
    executor = FailingExecutor(AssertionError("executor must not be called"))
    invalid = {"channel_id": "C1"}
    broker, actions, proposal, binding, lease, payload = _approved_slack_write(
        tmp_path, executor, payload=invalid,
    )

    assert broker.execute(lease, binding, payload) == (
        422, {"error": "payload does not match capability schema"},
    )
    assert actions.get(proposal["proposal_id"])["status"] == "approved"
    assert executor.calls == 0
