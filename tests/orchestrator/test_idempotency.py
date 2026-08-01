import threading

import pytest

from agents.orchestrator.action_repository import ActionRepository
from agents.orchestrator.reconciliation import reconcile_unknown_action
from libs.connectors.base import ProviderAuthority, ProviderNetworkError
from services.action_broker.app import ActionBroker


NOW = 1_700_000_000


class Clock:
    def __call__(self):
        return NOW


class Vault:
    def __init__(self, fail=None):
        self.calls = 0
        self.fail = fail

    def use_managed_oauth(self, _credential, _identity, operation):
        self.calls += 1
        if self.fail:
            raise self.fail
        return operation(b"secret")


class Executor:
    def __init__(self, fail=None):
        self.fail = fail

    def execute(self, *_args):
        if self.fail:
            raise self.fail
        return {"provider_id": "evt-1"}

    def read(self, *_args):
        return {}


class Connector:
    def refresh(self, refresh_token):
        assert refresh_token == "secret"
        return ProviderAuthority(
            "access-token",
            3600,
            frozenset(
                {"https://www.googleapis.com/auth/calendar.events"}
            ),
        )

    def scope_catalog(self):
        return {
            "calendar.create": "https://www.googleapis.com/auth/calendar.events"
        }


def _broker(repository, vault, executor=None):
    return ActionBroker(
        repository,
        object(),
        vault,
        executor or Executor(),
        Clock(),
        identity_verifier=lambda _url, _principal: True,
        agent_url_resolver=lambda _principal: "https://agent.example/a2a",
        credential_authorizer=lambda _binding: True,
        credential_connector=Connector(),
    )


def _approved(repository):
    payload = {"event": {"summary": "Interview"}}
    proposal = repository.create_proposal(
        "user:alice",
        "agent:calendar",
        "credential:google",
        "calendar.create",
        payload,
        NOW + 300,
        idempotency_key="idem-1",
    )
    repository.decide(proposal["proposal_id"], 1, "user:alice", True, NOW)
    binding = {
        key: proposal[key]
        for key in (
            "proposal_id",
            "version",
            "user_principal_id",
            "agent_principal_id",
            "credential_id",
            "capability_id",
            "payload_hash",
            "idempotency_key",
        )
    }
    binding.update(
        {"task_id": "task-1", "agent_url": "https://agent.example/a2a"}
    )
    lease = repository.issue_lease(
        "user:alice",
        "agent:calendar",
        "task-1",
        "credential:google",
        ["calendar.create"],
        NOW + 60,
    )
    return payload, proposal, binding, lease


def test_restart_returns_stored_receipt_without_second_provider_call(tmp_path):
    path = str(tmp_path / "actions.sqlite")
    repository = ActionRepository(path)
    payload, _, binding, lease = _approved(repository)
    vault = Vault()
    broker = _broker(repository, vault)
    assert broker.execute(lease, binding, payload)[0] == 200
    repository.close()

    restarted = ActionRepository(path)
    restarted_broker = _broker(restarted, vault)
    status, response = restarted_broker.execute(lease, binding, payload)
    assert status == 200
    assert response["receipt"]["provider_id"] == "evt-1"
    assert vault.calls == 1


def test_concurrent_requests_claim_once(tmp_path):
    repository = ActionRepository(str(tmp_path / "actions.sqlite"))
    payload, _, binding, lease = _approved(repository)
    vault = Vault()
    broker = _broker(repository, vault)
    barrier = threading.Barrier(3)
    statuses = []

    def execute():
        barrier.wait()
        statuses.append(broker.execute(lease, binding, payload)[0])

    workers = [threading.Thread(target=execute) for _ in range(2)]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join()
    assert 200 in statuses
    assert vault.calls == 1


def test_unknown_outcome_reconciles_without_duplicate(tmp_path):
    repository = ActionRepository(str(tmp_path / "actions.sqlite"))
    payload, proposal, binding, lease = _approved(repository)
    vault = Vault()
    broker = _broker(
        repository, vault,
        Executor(ProviderNetworkError("timeout after dispatch")),
    )
    assert broker.execute(lease, binding, payload) == (
        202,
        {"status": "execution_unknown"},
    )
    assert repository.get(proposal["proposal_id"])["status"] == "execution_unknown"

    unresolved = reconcile_unknown_action(
        repository, binding, lambda _binding: None, NOW + 1
    )
    assert unresolved["requires_resolution"] is True
    resolved = reconcile_unknown_action(
        repository,
        binding,
        lambda _binding: {"provider_id": "evt-found"},
        NOW + 2,
    )
    assert resolved["status"] == "completed"
    assert repository.get(proposal["proposal_id"])["status"] == "completed"
    assert vault.calls == 1


def test_dynamic_retry_scopes_idempotency_by_attempt_with_stable_effect_id(
    tmp_path,
):
    repository = ActionRepository(str(tmp_path / "actions.sqlite"))
    common = {
        "user_principal_id": "user:alice",
        "agent_principal_id": "agent:orchestrator",
        "credential_id": "credential:slack",
        "capability_id": "slack.message.send",
        "payload": {"channel_id": "C1", "text": "hello"},
        "expires_at": NOW + 300,
        "proposal_id": "proposal:revision:1:send",
        "idempotency_key": "workflow:revision:1:send",
        "workflow_revision_id": "revision:1",
        "step_id": "send",
        "plan_graph_hash": "graph:1",
        "connection_id": "conn:1",
    }
    first = repository.create_proposal(attempt=1, **common)
    assert repository.decide(
        first["proposal_id"], first["version"], "user:alice", True, NOW,
    )
    first_binding = {
        key: first[key] for key in (
            "proposal_id", "version", "user_principal_id",
            "agent_principal_id", "credential_id", "capability_id",
            "payload_hash", "idempotency_key", "workflow_revision_id",
            "step_id", "plan_graph_hash", "connection_id", "attempt",
        )
    }
    assert repository.consume_approval(first_binding, NOW) is not None
    assert repository.fail_execution(
        first["proposal_id"], first["version"], "safe rejection", NOW,
        unknown=False,
    )

    second = repository.create_proposal(attempt=2, **common)

    assert second["proposal_id"] == first["proposal_id"]
    assert second["version"] == first["version"] + 1
    assert second["attempt"] == 2
    assert second["idempotency_key"] != first["idempotency_key"]
    assert first["idempotency_key"].endswith(":attempt:1")
    assert second["idempotency_key"].endswith(":attempt:2")


@pytest.mark.parametrize("unknown", [False, True])
def test_dynamic_retry_is_blocked_while_prior_attempt_is_dispatched_or_unknown(
    tmp_path, unknown,
):
    repository = ActionRepository(str(tmp_path / ("actions-%s.sqlite" % unknown)))
    common = {
        "user_principal_id": "user:alice",
        "agent_principal_id": "agent:orchestrator",
        "credential_id": "credential:slack",
        "capability_id": "slack.message.send",
        "payload": {"channel_id": "C1", "text": "hello"},
        "expires_at": NOW + 300,
        "proposal_id": "proposal:revision:1:send",
        "idempotency_key": "workflow:revision:1:send",
        "workflow_revision_id": "revision:1",
        "step_id": "send",
        "plan_graph_hash": "graph:1",
        "connection_id": "conn:1",
    }
    first = repository.create_proposal(attempt=1, **common)
    assert repository.decide(
        first["proposal_id"], first["version"], "user:alice", True, NOW,
    )
    binding = {
        key: first[key] for key in (
            "proposal_id", "version", "user_principal_id",
            "agent_principal_id", "credential_id", "capability_id",
            "payload_hash", "idempotency_key", "workflow_revision_id",
            "step_id", "plan_graph_hash", "connection_id", "attempt",
        )
    }
    assert repository.consume_approval(binding, NOW) is not None
    assert repository.mark_dispatched(
        first["proposal_id"], first["version"], NOW,
    )
    if unknown:
        assert repository.fail_execution(
            first["proposal_id"], first["version"], "timeout", NOW,
            unknown=True,
        )

    with pytest.raises(ValueError, match="prior attempt"):
        repository.create_proposal(attempt=2, **common)
