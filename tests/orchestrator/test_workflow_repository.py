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
