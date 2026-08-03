import threading

import pytest

from agents.orchestrator.workflow_repository import WorkflowRepository


def _repository(tmp_path):
    return WorkflowRepository(str(tmp_path / "workflows.sqlite3"))


def _create(repository):
    run = repository.create_run("org:acme", "user:alice", "goal-hash", 10)
    revision = repository.create_revision(
        run["workflow_run_id"],
        "org:acme",
        "graph-hash-v1",
        [{
            "step_id": "step-1",
            "capability_id": "slack.message.send",
            "capability_version": "1.0.0",
            "connection_id": "conn:1",
            "descriptor_snapshot_hash": "descriptor-1",
            "input_hash": "input-1",
            "depends_on": [],
            "effect": "write",
        }],
        11,
    )
    return run, revision


def test_outbox_append_is_deduplicated_and_ordered_per_aggregate(tmp_path):
    repository = _repository(tmp_path)

    first = repository.append_outbox_event(
        "org:acme", "conversation", "conversation:1",
        "workflow.outcome", {"status": "complete"}, "revision:1:complete", 10,
    )
    duplicate = repository.append_outbox_event(
        "org:acme", "conversation", "conversation:1",
        "workflow.outcome", {"status": "complete"}, "revision:1:complete", 11,
    )
    second = repository.append_outbox_event(
        "org:acme", "conversation", "conversation:1",
        "workflow.outcome", {"status": "retry_wait"}, "revision:2:retry", 12,
    )

    assert duplicate == first
    assert first["aggregate_version"] == 1
    assert second["aggregate_version"] == 2
    first_claim = repository.claim_outbox_event("worker:a", 12, 5)
    assert first_claim["event_id"] == first["event_id"]
    assert repository.claim_outbox_event("worker:b", 12, 5) is None
    assert repository.complete_outbox_event(
        first_claim["event_id"], "org:acme", "worker:a", 13
    )
    assert repository.claim_outbox_event("worker:b", 13, 5)["event_id"] == second["event_id"]


def test_outbox_claim_has_one_winner_and_expired_claim_recovers(tmp_path):
    repository = _repository(tmp_path)
    repository.append_outbox_event(
        "org:acme", "conversation", "conversation:1",
        "workflow.outcome", {"status": "complete"}, "event:1", 10,
    )
    claims = []

    def claim(worker):
        claims.append(repository.claim_outbox_event(worker, 11, 5))

    threads = [threading.Thread(target=claim, args=("worker:a",)),
               threading.Thread(target=claim, args=("worker:b",))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    winners = [claim for claim in claims if claim]
    assert len(winners) == 1
    recovered = repository.claim_outbox_event("worker:c", 17, 5)
    assert recovered["event_id"] == winners[0]["event_id"]
    assert recovered["attempts"] == 2


def test_outbox_failure_retries_then_dead_letters_poison_event(tmp_path):
    repository = _repository(tmp_path)
    event = repository.append_outbox_event(
        "org:acme", "conversation", "conversation:1",
        "workflow.outcome", {"status": "complete"}, "poison", 10,
        max_attempts=2,
    )
    first = repository.claim_outbox_event("worker:a", 10, 5)
    assert repository.fail_outbox_event(
        event["event_id"], "org:acme", "worker:a", 10, "boom", 3
    ) == "retry"
    assert repository.claim_outbox_event("worker:b", 12, 5) is None
    second = repository.claim_outbox_event("worker:b", 13, 5)
    assert second["attempts"] == 2
    assert repository.fail_outbox_event(
        event["event_id"], "org:acme", "worker:b", 13, "boom again", 3
    ) == "dead_letter"
    assert repository.claim_outbox_event("worker:c", 20, 5) is None


def test_projection_watermark_rejects_stale_versions(tmp_path):
    repository = _repository(tmp_path)

    assert repository.advance_projection_watermark(
        "org:acme", "conversation", "conversation:1", 2, "event:2", 10
    )
    assert not repository.advance_projection_watermark(
        "org:acme", "conversation", "conversation:1", 1, "event:1", 11
    )
    assert not repository.advance_projection_watermark(
        "org:acme", "conversation", "conversation:1", 2, "event:2", 12
    )
    assert repository.get_projection_watermark(
        "org:acme", "conversation", "conversation:1"
    )["projected_version"] == 2


def test_completed_outbox_retention_purge_is_tenant_scoped(tmp_path):
    repository = _repository(tmp_path)
    acme = repository.append_outbox_event(
        "org:acme", "conversation", "conversation:1",
        "workflow.outcome", {}, "acme", 1,
    )
    other = repository.append_outbox_event(
        "org:other", "conversation", "conversation:1",
        "workflow.outcome", {}, "other", 1,
    )
    for tenant, event in (("org:acme", acme), ("org:other", other)):
        claim = repository.claim_outbox_event("worker", 2, 5, tenant_id=tenant)
        assert repository.complete_outbox_event(
            claim["event_id"], tenant, "worker", 3
        )

    assert repository.purge_completed_outbox("org:acme", 4) == 1
    assert repository.get_outbox_event(other["event_id"], "org:other") is not None


def test_revision_and_step_bindings_are_immutable(tmp_path):
    repository = _repository(tmp_path)
    run, revision = _create(repository)
    fetched = repository.get_revision(
        run["workflow_run_id"], revision["workflow_revision_id"], "org:acme"
    )
    assert fetched["plan_graph_hash"] == "graph-hash-v1"
    assert fetched["steps"][0]["connection_id"] == "conn:1"


def test_two_workers_cannot_claim_same_step(tmp_path):
    repository = _repository(tmp_path)
    run, revision = _create(repository)
    claims = []

    def claim(worker):
        claims.append(repository.claim_ready_step(
            run["workflow_run_id"], revision["workflow_revision_id"],
            "org:acme", worker, 20, 60
        ))

    threads = [threading.Thread(target=claim, args=("worker-a",)),
               threading.Thread(target=claim, args=("worker-b",))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len([claim for claim in claims if claim is not None]) == 1


def test_replan_does_not_reuse_prior_revision_approval(tmp_path):
    repository = _repository(tmp_path)
    run, first = _create(repository)
    repository.record_approval(
        run["workflow_run_id"], first["workflow_revision_id"],
        "org:acme", "graph-hash-v1", "user:alice", 12
    )
    second = repository.create_revision(
        run["workflow_run_id"], "org:acme", "graph-hash-v2", [{
            "step_id": "step-1",
            "capability_id": "slack.message.send",
            "capability_version": "1.0.0",
            "connection_id": "conn:1",
            "descriptor_snapshot_hash": "descriptor-2",
            "input_hash": "input-1",
            "depends_on": [],
            "effect": "write",
        }], 13
    )

    assert repository.is_revision_approved(
        run["workflow_run_id"], first["workflow_revision_id"],
        "org:acme", "graph-hash-v1"
    )
    assert not repository.is_revision_approved(
        run["workflow_run_id"], second["workflow_revision_id"],
        "org:acme", "graph-hash-v2"
    )


def test_superseded_revision_is_not_authorized_after_a_running_step_was_claimed(
    tmp_path,
):
    repository = _repository(tmp_path)
    run, first = _create(repository)
    repository.record_approval(
        run["workflow_run_id"], first["workflow_revision_id"],
        "org:acme", "graph-hash-v1", "user:alice", 12,
    )
    claim = repository.claim_ready_step(
        run["workflow_run_id"], first["workflow_revision_id"],
        "org:acme", "worker-a", 13, 60,
    )
    assert claim is not None

    second = repository.create_revision(
        run["workflow_run_id"], "org:acme", "graph-hash-v2", [{
            "step_id": "step-1",
            "capability_id": "slack.message.send",
            "capability_version": "1.0.0",
            "connection_id": "conn:1",
            "descriptor_snapshot_hash": "descriptor-2",
            "input_hash": "input-2",
            "depends_on": [],
            "effect": "write",
        }], 14,
    )

    assert repository.get_run(
        run["workflow_run_id"], "org:acme"
    )["current_revision_id"] == second["workflow_revision_id"]
    assert repository.get_revision(
        run["workflow_run_id"], first["workflow_revision_id"], "org:acme"
    )["status"] == "superseded"
    assert not repository.is_step_authorized(
        run["workflow_run_id"], first["workflow_revision_id"],
        "org:acme", "graph-hash-v1", "write", 15,
    )


def test_completed_current_revision_passes_the_executor_authorization_gate(
    tmp_path,
):
    repository = _repository(tmp_path)
    run, revision = _create(repository)
    repository.record_approval(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:acme", "graph-hash-v1", "user:alice", 12,
    )
    claim = repository.claim_ready_step(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:acme", "worker-a", 13, 60,
    )
    repository.persist_completion(
        revision["workflow_revision_id"], "step-1", "org:acme",
        claim["attempt"], {"provider_id": "123.45"},
        {"attestation_id": "attestation:1"}, 14,
    )

    assert repository.get_revision(
        run["workflow_run_id"], revision["workflow_revision_id"], "org:acme"
    )["status"] == "completed"
    assert repository.is_step_authorized(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:acme", "graph-hash-v1", "write", 15,
    )


def test_cancelled_current_revision_is_not_authorized(tmp_path):
    repository = _repository(tmp_path)
    run, revision = _create(repository)
    repository.record_approval(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:acme", "graph-hash-v1", "user:alice", 12,
    )
    assert repository.cancel_revision(
        run["workflow_run_id"], revision["workflow_revision_id"], "org:acme"
    )

    assert not repository.is_step_authorized(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:acme", "graph-hash-v1", "write", 13,
    )


def test_revision_approval_expires_for_execution(tmp_path):
    repository = _repository(tmp_path)
    run, revision = _create(repository)
    repository.record_approval(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:acme", "graph-hash-v1", "user:alice", 100, ttl_seconds=30,
    )

    assert repository.is_revision_approved(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:acme", "graph-hash-v1", 130,
    )
    assert not repository.is_revision_approved(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:acme", "graph-hash-v1", 131,
    )


def test_completion_and_verification_survive_repository_restart(tmp_path):
    database = str(tmp_path / "workflows.sqlite3")
    repository = WorkflowRepository(database)
    run, revision = _create(repository)
    claim = repository.claim_ready_step(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:acme", "worker-a", 20, 60
    )
    persisted = repository.persist_completion(
        revision["workflow_revision_id"], "step-1", "org:acme",
        claim["attempt"], {"provider": "slack", "provider_id": "123.45"},
        {"attestation_id": "attestation:1", "signature": "signed"}, 21
    )
    assert persisted["verification_status"] == "pending"

    restarted = WorkflowRepository(database)
    fetched = restarted.get_revision(
        run["workflow_run_id"], revision["workflow_revision_id"], "org:acme"
    )
    assert fetched["steps"][0]["execution_status"] == "completed"
    assert fetched["steps"][0]["verification_status"] == "pending"
    assert fetched["status"] == "completed"
    assert restarted.get_run(run["workflow_run_id"], "org:acme")["status"] == "completed"
    assert restarted.set_verification_status(
        revision["workflow_revision_id"], "step-1", "org:acme", "verified"
    )


def test_existing_database_gets_new_step_columns_and_receipts_are_step_scoped(tmp_path):
    database = str(tmp_path / "workflows.sqlite3")
    repository = WorkflowRepository(database)
    run = repository.create_run("org:acme", "user:alice", "goal", 1)
    revision = repository.create_revision(run["workflow_run_id"], "org:acme", "graph", [
        {"step_id": name, "capability_id": "synthetic.read", "capability_version": "1",
         "connection_id": "conn:1", "descriptor_snapshot_hash": "d", "input_hash": "i",
         "input": {}, "depends_on": [], "effect": "read"}
        for name in ("a", "b")
    ], 2)
    for number, name in enumerate(("a", "b"), 3):
        claim = repository.claim_ready_step(run["workflow_run_id"], revision["workflow_revision_id"], "org:acme", "worker", number, 60)
        repository.persist_completion(revision["workflow_revision_id"], claim["step_id"], "org:acme", claim["attempt"], {"same": True}, None, number)
    fetched = repository.get_revision(run["workflow_run_id"], revision["workflow_revision_id"], "org:acme")
    assert [step["execution_status"] for step in fetched["steps"]] == ["completed", "completed"]


def test_expired_write_claim_requires_reconciliation_instead_of_retry(tmp_path):
    repository = _repository(tmp_path)
    run, revision = _create(repository)
    repository.claim_ready_step(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:acme", "dead-worker", 20, 5,
    )

    assert repository.recover_expired_claims(26) == 1
    fetched = repository.get_revision(
        run["workflow_run_id"], revision["workflow_revision_id"], "org:acme"
    )
    assert fetched["steps"][0]["execution_status"] == "execution_unknown"


def test_reconciliation_cannot_complete_write_without_evidence(tmp_path):
    repository = _repository(tmp_path)
    run, revision = _create(repository)
    claim = repository.claim_ready_step(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:acme", "worker", 20, 5,
    )
    repository.mark_execution_unknown(
        revision["workflow_revision_id"], "step-1", "org:acme", "timeout"
    )

    with pytest.raises(ValueError, match="receipt and signed attestation"):
        repository.apply_reconciliation(
            revision["workflow_revision_id"], "step-1", "org:acme",
            claim["attempt"], {"execution_status": "completed", "provider_id": "123.45"},
        )


def test_only_kill_switch_policy_pause_can_resume(tmp_path):
    repository = _repository(tmp_path)
    run, revision = _create(repository)
    repository.pause_by_policy(
        revision["workflow_revision_id"], "step-1", "org:acme",
        "dispatch policy disabled",
    )
    assert repository.resume_policy_paused() == 1
    fetched = repository.get_revision(
        run["workflow_run_id"], revision["workflow_revision_id"], "org:acme"
    )
    assert fetched["steps"][0]["execution_status"] == "queued"

    repository.pause_by_policy(
        revision["workflow_revision_id"], "step-1", "org:acme",
        "connection binding changed",
    )
    assert repository.resume_policy_paused() == 0


class _ContentCrypto:
    def __init__(self):
        self.values = {}

    def seal(self, value, context):
        key = "ciphertext-%d" % len(self.values)
        self.values[key] = value
        return {"ciphertext": key, "context": context}

    def open(self, envelope, context):
        assert envelope["context"] == context
        return self.values[envelope["ciphertext"]]


def test_workflow_content_is_encrypted_and_purged_after_ttl(tmp_path):
    repository = WorkflowRepository(
        str(tmp_path / "encrypted.sqlite3"), content_crypto=_ContentCrypto()
    )
    run = repository.create_run("org:acme", "user:alice", "goal", 10)
    revision = repository.create_revision(
        run["workflow_run_id"], "org:acme", "graph", [{
            "step_id": "read", "capability_id": "slack.thread.read",
            "capability_version": "1", "connection_id": "conn:1",
            "descriptor_snapshot_hash": "d", "input_hash": "i",
            "input": {"channel_id": "C-secret"}, "depends_on": [], "effect": "read",
        }], 11, content_ttl_seconds=1,
    )
    raw = repository._connection.execute(
        "SELECT input_json FROM workflow_steps WHERE workflow_revision_id = ?",
        (revision["workflow_revision_id"],),
    ).fetchone()["input_json"]
    assert "C-secret" not in raw
    assert repository.get_revision(
        run["workflow_run_id"], revision["workflow_revision_id"], "org:acme"
    )["steps"][0]["input"] == {"channel_id": "C-secret"}

    claim = repository.claim_ready_step(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:acme", "worker", 11, 60,
    )
    repository.persist_completion(
        revision["workflow_revision_id"], "read", "org:acme", claim["attempt"],
        {"id": "receipt"}, None, 12, output={"text": "private summary"},
    )
    assert repository.purge_expired_content(13) == 1
    purged = repository.get_revision(
        run["workflow_run_id"], revision["workflow_revision_id"], "org:acme"
    )["steps"][0]
    assert purged["input"] == {}
    assert purged["output"] == {}


def test_production_workflow_repository_requires_kms_key(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("TESSERA_WORKFLOW_KMS_KEY_ID", raising=False)
    with pytest.raises(RuntimeError, match="KMS_KEY_ID"):
        WorkflowRepository.from_environment(
            str(tmp_path / "workflow.sqlite3"), "service:test"
        )


def test_authenticated_read_authorization_never_covers_a_write(tmp_path):
    repository = _repository(tmp_path)
    run = repository.create_run("org:acme", "user:alice", "goal", 1)
    read = repository.create_revision(run["workflow_run_id"], "org:acme", "read-graph", [{
        "step_id": "read", "capability_id": "slack.conversation.read",
        "capability_version": "1", "connection_id": "conn:1",
        "descriptor_snapshot_hash": "d", "input_hash": "i", "input": {},
        "depends_on": [], "effect": "read",
    }], 2)
    assert repository.authorize_requested_read(
        run["workflow_run_id"], read["workflow_revision_id"], "org:acme",
        "read-graph", "user:alice", 3,
    )
    assert repository.revision_authorization_mode(
        run["workflow_run_id"], read["workflow_revision_id"], "org:acme",
        "read-graph", 3,
    ) == "requested_read"

    mixed = repository.create_revision(run["workflow_run_id"], "org:acme", "mixed", [
        {"step_id": "read", "capability_id": "slack.conversation.read", "capability_version": "1", "connection_id": "conn:1", "descriptor_snapshot_hash": "d", "input_hash": "i", "input": {}, "depends_on": [], "effect": "read"},
        {"step_id": "write", "capability_id": "slack.message.send", "capability_version": "1", "connection_id": "conn:1", "descriptor_snapshot_hash": "d", "input_hash": "i", "input": {}, "depends_on": ["read"], "effect": "write"},
    ], 4)
    with pytest.raises(ValueError, match="read-only"):
        repository.authorize_requested_read(
            run["workflow_run_id"], mixed["workflow_revision_id"], "org:acme",
            "mixed", "user:alice", 5,
        )
    assert repository.revision_authorization_mode(
        run["workflow_run_id"], mixed["workflow_revision_id"], "org:acme",
        "mixed", 5,
    ) is None


def test_recovery_options_only_offer_safe_read_retry(tmp_path):
    repository = _repository(tmp_path)
    run = repository.create_run("org:acme", "user:alice", "goal", 1)
    revision = repository.create_revision(run["workflow_run_id"], "org:acme", "graph", [{
        "step_id": "read", "capability_id": "slack.channels.list",
        "capability_version": "1", "connection_id": "conn:1",
        "descriptor_snapshot_hash": "d", "input_hash": "i", "input": {},
        "depends_on": [], "effect": "read",
    }], 2)
    claim = repository.claim_ready_step(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:acme", "worker", 3, 60,
    )
    repository.release_for_retry(
        revision["workflow_revision_id"], "read", "org:acme", "rate limited", 30
    )
    current = repository.get_revision(
        run["workflow_run_id"], revision["workflow_revision_id"], "org:acme"
    )
    assert repository.recovery_options(current)["retryableStepIds"] == ["read"]
    assert repository.retry_safe_read(
        run["workflow_run_id"], revision["workflow_revision_id"],
        claim["step_id"], "org:acme",
    )
    current = repository.get_revision(
        run["workflow_run_id"], revision["workflow_revision_id"], "org:acme"
    )
    assert repository.recovery_options(current)["retryableStepIds"] == []


def test_slack_entity_snapshots_are_minimized_versioned_and_idempotent(tmp_path):
    repository = _repository(tmp_path)
    conversation = repository.create_conversation(
        "org:acme", "user:alice", 10, conversation_id="conversation:entities"
    )

    first = repository.store_slack_conversation_entity(
        conversation["conversation_id"], "org:acme", "user:alice",
        "channel", "conn:slack", "T1", "C1",
        {
            "id": "C1", "name": "general", "is_private": False,
            "is_archived": False, "topic": "must not persist",
            "email": "must-not-persist@example.com",
        },
        {"source": "conversations.list", "cursor": "page:1"},
        11, 71, expected_state_version=1,
    )
    replay = repository.store_slack_conversation_entity(
        conversation["conversation_id"], "org:acme", "user:alice",
        "channel", "conn:slack", "T1", "C1",
        {"id": "C1", "name": "general", "is_private": False,
         "is_archived": False, "topic": "changed but excluded"},
        {"source": "conversations.list", "cursor": "page:2"},
        12, 72, expected_state_version=1,
    )
    changed = repository.store_slack_conversation_entity(
        conversation["conversation_id"], "org:acme", "user:alice",
        "channel", "conn:slack", "T1", "C1",
        {"id": "C1", "name": "announcements", "is_private": False,
         "is_archived": False},
        {"source": "conversations.list", "cursor": "page:3"},
        13, 73, expected_state_version=1,
    )

    assert first["entity"] == {
        "id": "C1", "name": "general", "is_private": False,
        "is_archived": False,
    }
    assert replay["entity_ref_id"] == first["entity_ref_id"]
    assert replay["entity_version"] == 1
    assert changed["entity_ref_id"] != first["entity_ref_id"]
    assert changed["entity_version"] == 2
    rows = repository._connection.execute(
        "SELECT entity_version, superseded_at FROM slack_conversation_entities "
        "ORDER BY entity_version"
    ).fetchall()
    assert [dict(row) for row in rows] == [
        {"entity_version": 1, "superseded_at": 13},
        {"entity_version": 2, "superseded_at": None},
    ]


def test_slack_entity_reads_require_owner_binding_and_freshness(tmp_path):
    repository = _repository(tmp_path)
    repository.create_conversation(
        "org:acme", "user:alice", 10, conversation_id="conversation:entities"
    )
    stored = repository.store_slack_conversation_entity(
        "conversation:entities", "org:acme", "user:alice", "user",
        "conn:slack", "T1", "U1",
        {
            "id": "U1", "display_name": "Maria", "real_name": "Maria R",
            "handle": "maria", "email": "private@example.com",
            "profile": {"phone": "private"},
        },
        {"source": "users.list"}, 11, 20, expected_state_version=1,
    )

    assert repository.get_slack_conversation_entity(
        stored["entity_ref_id"], "conversation:entities", "org:acme",
        "user:alice", 19,
    )["entity"] == {
        "id": "U1", "display_name": "Maria", "real_name": "Maria R",
        "handle": "maria",
    }
    assert repository.get_slack_conversation_entity(
        stored["entity_ref_id"], "conversation:entities", "org:other",
        "user:alice", 19,
    ) is None
    assert repository.get_slack_conversation_entity(
        stored["entity_ref_id"], "conversation:entities", "org:acme",
        "user:bob", 19,
    ) is None
    assert repository.get_slack_conversation_entity(
        stored["entity_ref_id"], "conversation:entities", "org:acme",
        "user:alice", 21,
    ) is None
    assert repository.get_slack_conversation_entity(
        stored["entity_ref_id"], "conversation:entities", "org:acme",
        "user:alice", 21, include_stale=True,
    )["stale"] is True

    with pytest.raises(RuntimeError, match="conversation version conflict"):
        repository.store_slack_conversation_entity(
            "conversation:entities", "org:acme", "user:alice", "user",
            "conn:slack", "T1", "U2", {"id": "U2"},
            {"source": "users.list"}, 12, 20, expected_state_version=2,
        )

    repository.close_conversation(
        "conversation:entities", "org:acme", "user:alice", 22
    )
    assert repository.get_slack_conversation_entity(
        stored["entity_ref_id"], "conversation:entities", "org:acme",
        "user:alice", 22, include_stale=True,
    ) is None
