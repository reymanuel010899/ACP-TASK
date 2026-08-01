import copy
import json

import pytest

from agents.orchestrator.action_repository import ActionRepository
from agents.orchestrator import tools as orchestrator_tools
from libs.connectors.base import ProviderAuthority
from services.action_broker.app import (
    ActionBroker,
    _safe_receipt,
    oauth_connection_authorizer,
)


NOW = 1_700_000_000


def test_safe_receipt_preserves_safe_nested_provider_data():
    receipt = {
        "provider": "slack",
        "messages": [{"text": "safe", "metadata": {"page": 1}}],
    }
    original = copy.deepcopy(receipt)

    assert _safe_receipt(receipt) is receipt
    assert receipt == original


@pytest.mark.parametrize("receipt", [
    {"metadata": {"access_token": "xoxb-secret"}},
    {"items": [{"details": {"Refresh_Token": "sealed-secret"}}]},
    {"items": [[{"AUTHORIZATION": "Bearer secret"}]]},
    {"result": {"token": "secret"}},
])
def test_safe_receipt_rejects_authority_material_at_any_depth(receipt):
    with pytest.raises(ValueError, match="forbidden authority material"):
        _safe_receipt(receipt)


def test_safe_receipt_rejects_excessive_depth_items_and_serialized_size():
    too_deep = {"leaf": "value"}
    for _ in range(10):
        too_deep = {"nested": too_deep}

    with pytest.raises(ValueError, match="depth limit"):
        _safe_receipt(too_deep)
    with pytest.raises(ValueError, match="item limit"):
        _safe_receipt({"items": list(range(1001))})
    with pytest.raises(ValueError, match="size limit"):
        _safe_receipt({"value": "x" * 70_000})


def test_tenant_bound_installation_authorizes_verified_member_execution():
    class Connections:
        def get_installation(self, connection_id, tenant_id):
            assert (connection_id, tenant_id) == ("conn:slack", "org:local")
            return {
                "principal_id": "user:owner",
                "credential_id": "credential:slack",
                "status": "connected",
                "enabled_capabilities": ["slack.channels.list"],
            }

    assert oauth_connection_authorizer(Connections())({
        "connection_id": "conn:slack", "tenant_id": "org:local",
        "user_principal_id": "user:member",
        "credential_id": "credential:slack",
        "capability_id": "slack.channels.list",
    })


class Clock(object):
    def __call__(self):
        return NOW


class Sessions(object):
    pass


class Vault(object):
    def __init__(self):
        self.calls = []

    def use_managed_oauth(self, credential_id, identity, operation):
        self.calls.append((credential_id, identity))
        return operation(b"provider-secret-token")


class Executor(object):
    def __init__(self):
        self.writes = []
        self.reads = []

    def execute(self, capability, payload, context):
        self.writes.append((capability, payload, dict(context)))
        return {
            "provider": "google",
            "capability_id": capability,
            "provider_id": "evt-1",
        }

    def read(self, capability, payload, context):
        self.reads.append((capability, payload, dict(context)))
        return {"items": [{"start": "2026-07-30T11:00:00-04:00"}]}


class Connector(object):
    def refresh(self, refresh_token):
        assert refresh_token == "provider-secret-token"
        return ProviderAuthority(
            "short-lived-access-token",
            3600,
            frozenset(
                {
                    "https://www.googleapis.com/auth/calendar.events",
                    "https://www.googleapis.com/auth/calendar.readonly",
                    "https://www.googleapis.com/auth/gmail.send",
                }
            ),
        )

    def scope_catalog(self):
        return {
            "calendar.create": "https://www.googleapis.com/auth/calendar.events",
            "calendar.read": "https://www.googleapis.com/auth/calendar.readonly",
            "gmail.send": "https://www.googleapis.com/auth/gmail.send",
        }


def _stack(tmp_path):
    actions = ActionRepository(str(tmp_path / "actions.sqlite"))
    vault = Vault()
    executor = Executor()
    broker = ActionBroker(
        actions,
        Sessions(),
        vault,
        executor,
        Clock(),
        identity_verifier=lambda _url, _principal: True,
        agent_url_resolver=lambda _principal: "https://agent.example/a2a",
        credential_authorizer=lambda _binding: True,
        credential_connector=Connector(),
    )
    return broker, actions, vault, executor


def _binding(proposal, task_id="task-1"):
    return {
        "proposal_id": proposal["proposal_id"],
        "version": proposal["version"],
        "user_principal_id": proposal["user_principal_id"],
        "agent_principal_id": proposal["agent_principal_id"],
        "task_id": task_id,
        "credential_id": proposal["credential_id"],
        "capability_id": proposal["capability_id"],
        "payload_hash": proposal["payload_hash"],
        "idempotency_key": proposal["idempotency_key"],
        "agent_url": "https://agent.example/a2a",
    }


def test_approved_write_executes_once_and_returns_only_receipt(tmp_path):
    broker, actions, vault, executor = _stack(tmp_path)
    payload = {"event": {"summary": "Interview"}}
    proposal = actions.create_proposal(
        "user:alice", "agent:calendar", "credential:google",
        "calendar.create", payload, NOW + 300,
    )
    actions.decide(proposal["proposal_id"], 1, "user:alice", True, NOW)
    binding = _binding(proposal)
    lease = actions.issue_lease(
        "user:alice", "agent:calendar", "task-1", "credential:google",
        ["calendar.create"], NOW + 60,
    )

    status, response = broker.execute(lease, binding, payload)
    assert status == 200
    assert response["receipt"]["provider_id"] == "evt-1"
    assert "provider-secret-token" not in json.dumps(response)
    assert executor.writes[0][2]["access_token"] == "short-lived-access-token"
    assert len(executor.writes) == 1
    replay_status, replay = broker.execute(lease, binding, payload)
    assert replay_status == 200
    assert replay == response
    assert len(executor.writes) == 1


def test_authorized_read_is_filtered_but_wrong_lease_scope_and_task_fail(tmp_path):
    broker, actions, _, executor = _stack(tmp_path)
    proposal = actions.create_proposal(
        "user:alice", "agent:calendar", "credential:google",
        "calendar.read", {}, NOW + 300,
    )
    binding = _binding(proposal)
    lease = actions.issue_lease(
        "user:alice", "agent:calendar", "task-1", "credential:google",
        ["calendar.read"], NOW + 60,
    )
    status, response = broker.execute(lease, binding, {})
    assert status == 200
    assert response == {
        "receipt": {"items": [{"start": "2026-07-30T11:00:00-04:00"}]}
    }
    assert len(executor.reads) == 1
    assert broker.execute(lease, binding, {})[0] == 403
    assert len(executor.reads) == 1

    wrong = dict(binding, task_id="task-other")
    assert broker.execute(lease, wrong, {})[0] == 403
    wrong = dict(binding, capability_id="gmail.read")
    assert broker.execute(lease, wrong, {})[0] == 403


def test_payload_approval_mismatch_and_missing_lease_never_call_provider(tmp_path):
    broker, actions, vault, executor = _stack(tmp_path)
    approved = {"raw": "message-a"}
    proposal = actions.create_proposal(
        "user:alice", "agent:mail", "credential:google",
        "gmail.send", approved, NOW + 300,
    )
    actions.decide(proposal["proposal_id"], 1, "user:alice", True, NOW)
    binding = _binding(proposal)
    lease = actions.issue_lease(
        "user:alice", "agent:mail", "task-1", "credential:google",
        ["gmail.send"], NOW + 60,
    )

    assert broker.execute(None, binding, approved)[0] == 403
    assert broker.execute(lease, binding, {"raw": "changed"})[0] == 403
    assert vault.calls == []
    assert executor.writes == []


def test_inactive_or_unowned_credential_never_reaches_vault(tmp_path):
    broker, actions, vault, executor = _stack(tmp_path)
    payload = {"event": {"summary": "Interview"}}
    proposal = actions.create_proposal(
        "user:alice",
        "agent:calendar",
        "credential:other-user",
        "calendar.create",
        payload,
        NOW + 300,
    )
    actions.decide(proposal["proposal_id"], 1, "user:alice", True, NOW)
    binding = _binding(proposal)
    lease = actions.issue_lease(
        "user:alice",
        "agent:calendar",
        "task-1",
        "credential:other-user",
        ["calendar.create"],
        NOW + 60,
    )
    broker.credential_authorizer = lambda _binding: False

    assert broker.execute(lease, binding, payload)[0] == 403
    assert vault.calls == []
    assert executor.writes == []


def test_provider_accept_routes_privileged_operation_through_broker(
    tmp_path, monkeypatch
):
    broker, actions, vault, executor = _stack(tmp_path)
    payload = {"event": {"summary": "Interview"}}
    proposal = actions.create_proposal(
        "user:alice",
        "agent:calendar",
        "credential:google",
        "calendar.create",
        payload,
        NOW + 300,
    )
    actions.decide(proposal["proposal_id"], 1, "user:alice", True, NOW)
    binding = _binding(proposal)
    lease = actions.issue_lease(
        "user:alice",
        "agent:calendar",
        "task-1",
        "credential:google",
        ["calendar.create"],
        NOW + 60,
    )
    monkeypatch.setattr(
        orchestrator_tools,
        "_a2a_send",
        lambda *_args: {
            "type": "task.result",
            "output": {"prepared": True},
            "broker_request": {
                "lease": lease,
                "binding": binding,
                "payload": payload,
            },
        },
    )

    result = orchestrator_tools.provider_accept(
        "https://agent.example/a2a",
        "task-1",
        1,
        action_broker=broker,
    )

    assert result["output"] == {"prepared": True}
    assert result["broker_result"]["receipt"]["provider_id"] == "evt-1"
    assert "broker_request" not in result
    assert "provider-secret-token" not in json.dumps(result)
    assert len(vault.calls) == 1
    assert len(executor.writes) == 1


def test_provider_accept_fails_closed_without_broker(monkeypatch):
    monkeypatch.setattr(
        orchestrator_tools,
        "_a2a_send",
        lambda *_args: {
            "broker_request": {
                "lease": "lease",
                "binding": {},
                "payload": {},
            }
        },
    )

    try:
        orchestrator_tools.provider_accept(
            "https://agent.example/a2a", "task-1", 1
        )
    except orchestrator_tools.P2PError as exc:
        assert "unavailable broker" in str(exc)
    else:
        raise AssertionError("provider operation must fail closed")


def test_provider_accept_preserves_unknown_execution_status(monkeypatch):
    class UnknownBroker(object):
        def execute(self, _lease, _binding, _payload):
            return 202, {"status": "execution_unknown"}

    monkeypatch.setattr(
        orchestrator_tools,
        "_a2a_send",
        lambda *_args: {
            "broker_request": {
                "lease": "lease",
                "binding": {"capability_id": "calendar.create"},
                "payload": {},
            }
        },
    )

    result = orchestrator_tools.provider_accept(
        "https://agent.example/a2a",
        "task-1",
        1,
        action_broker=UnknownBroker(),
    )

    assert result["broker_status"] == "execution_unknown"
