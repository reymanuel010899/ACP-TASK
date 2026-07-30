from agents.orchestrator.action_repository import ActionRepository
from libs.connectors.base import ProviderAuthority
from services.action_broker.app import ActionBroker


NOW = 1_700_000_000


class Vault:
    def __init__(self):
        self.calls = 0

    def use_managed_oauth(self, _credential, _identity, operation):
        self.calls += 1
        return operation(b"token")


class Executor:
    def execute(self, *_args):
        return {"provider_id": "evt-1"}

    def read(self, *_args):
        return {"items": []}


class Connector:
    def refresh(self, refresh_token):
        assert refresh_token == "token"
        return ProviderAuthority(
            "access-token",
            3600,
            frozenset(
                {
                    "https://www.googleapis.com/auth/calendar.events",
                    "https://www.googleapis.com/auth/calendar.readonly",
                }
            ),
        )

    def scope_catalog(self):
        return {
            "calendar.create": "https://www.googleapis.com/auth/calendar.events",
            "calendar.read": "https://www.googleapis.com/auth/calendar.readonly",
        }


def _write(repository):
    payload = {"event": {"summary": "Interview"}}
    proposal = repository.create_proposal(
        "user:alice",
        "agent:calendar",
        "credential:google",
        "calendar.create",
        payload,
        NOW + 60,
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
    return payload, binding, lease


def test_side_effect_reverifies_immediately_before_provider_call(tmp_path):
    repository = ActionRepository(str(tmp_path / "actions.sqlite"))
    payload, binding, lease = _write(repository)
    calls = []
    vault = Vault()
    broker = ActionBroker(
        repository,
        object(),
        vault,
        Executor(),
        clock=lambda: NOW,
        identity_verifier=lambda url, principal: calls.append(
            (url, principal)
        ) or True,
        agent_url_resolver=lambda _principal: "https://agent.example/a2a",
        credential_authorizer=lambda _binding: True,
        credential_connector=Connector(),
    )
    assert broker.execute(lease, binding, payload)[0] == 200
    assert calls == [
        ("https://agent.example/a2a", "agent:calendar")
    ]
    assert vault.calls == 1


def test_failed_challenge_blocks_effect_and_pure_read_skips_challenge(tmp_path):
    repository = ActionRepository(str(tmp_path / "actions.sqlite"))
    payload, binding, lease = _write(repository)
    vault = Vault()
    broker = ActionBroker(
        repository,
        object(),
        vault,
        Executor(),
        clock=lambda: NOW,
        identity_verifier=lambda *_args: False,
        agent_url_resolver=lambda _principal: "https://agent.example/a2a",
        credential_authorizer=lambda _binding: True,
        credential_connector=Connector(),
    )
    assert broker.execute(lease, binding, payload)[0] == 403
    assert vault.calls == 0

    read_proposal = repository.create_proposal(
        "user:alice",
        "agent:calendar",
        "credential:google",
        "calendar.read",
        {},
        NOW + 60,
    )
    read_binding = {
        key: read_proposal[key]
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
    read_binding["task_id"] = "task-read"
    read_lease = repository.issue_lease(
        "user:alice",
        "agent:calendar",
        "task-read",
        "credential:google",
        ["calendar.read"],
        NOW + 60,
    )
    assert broker.execute(read_lease, read_binding, {})[0] == 200
    assert vault.calls == 1
