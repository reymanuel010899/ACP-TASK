import threading

from agents.orchestrator.action_repository import (
    ActionRepository,
    canonical_payload_hash,
)


NOW = 1_700_000_000


def _proposal(repository, **overrides):
    values = {
        "user_principal_id": "user:alice",
        "agent_principal_id": "agent:calendar",
        "credential_id": "credential:google",
        "capability_id": "calendar.create",
        "payload": {"summary": "Interview", "start": "2026-07-30T11:00:00-04:00"},
        "expires_at": NOW + 300,
        "idempotency_key": "idem-1",
    }
    values.update(overrides)
    return repository.create_proposal(**values)


def _binding(proposal):
    return {
        "proposal_id": proposal["proposal_id"],
        "version": proposal["version"],
        "user_principal_id": proposal["user_principal_id"],
        "agent_principal_id": proposal["agent_principal_id"],
        "credential_id": proposal["credential_id"],
        "capability_id": proposal["capability_id"],
        "payload_hash": proposal["payload_hash"],
        "idempotency_key": proposal["idempotency_key"],
    }


def test_zero_cost_irreversible_action_still_requires_exact_approval(tmp_path):
    repository = ActionRepository(str(tmp_path / "actions.sqlite"))
    proposal = _proposal(repository)

    assert repository.consume_approval(_binding(proposal), NOW) is None
    assert repository.decide(
        proposal["proposal_id"], proposal["version"], "user:alice", True, NOW
    )
    consumed = repository.consume_approval(_binding(proposal), NOW)
    assert consumed["status"] == "executing"
    assert repository.consume_approval(_binding(proposal), NOW) is None


def test_modified_payload_identity_account_and_expiry_fail_closed(tmp_path):
    repository = ActionRepository(str(tmp_path / "actions.sqlite"))
    for field, invalid in (
        ("payload_hash", canonical_payload_hash({"changed": True})),
        ("user_principal_id", "user:bob"),
        ("agent_principal_id", "agent:attacker"),
        ("credential_id", "credential:other"),
    ):
        proposal = _proposal(
            repository, idempotency_key="idem-%s" % field
        )
        repository.decide(
            proposal["proposal_id"], proposal["version"], "user:alice", True, NOW
        )
        binding = _binding(proposal)
        binding[field] = invalid
        assert repository.consume_approval(binding, NOW) is None

    expired = _proposal(repository, idempotency_key="idem-expired", expires_at=NOW - 1)
    assert not repository.decide(
        expired["proposal_id"], expired["version"], "user:alice", True, NOW
    )


def test_new_version_supersedes_old_approval_and_concurrent_consume_has_one_winner(
    tmp_path,
):
    repository = ActionRepository(str(tmp_path / "actions.sqlite"))
    first = _proposal(repository, proposal_id="proposal-stable")
    repository.decide("proposal-stable", 1, "user:alice", True, NOW)
    second = _proposal(
        repository,
        proposal_id="proposal-stable",
        idempotency_key="idem-2",
        payload={"summary": "Interview", "start": "2026-07-30T12:00:00-04:00"},
    )
    assert repository.consume_approval(_binding(first), NOW) is None
    repository.decide("proposal-stable", 2, "user:alice", True, NOW)

    barrier = threading.Barrier(3)
    results = []

    def consume():
        barrier.wait()
        results.append(repository.consume_approval(_binding(second), NOW))

    threads = [threading.Thread(target=consume) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert sum(result is not None for result in results) == 1


def test_rejection_never_consumes(tmp_path):
    repository = ActionRepository(str(tmp_path / "actions.sqlite"))
    proposal = _proposal(repository)
    assert repository.decide(
        proposal["proposal_id"], 1, "user:alice", False, NOW
    )
    assert repository.consume_approval(_binding(proposal), NOW) is None
