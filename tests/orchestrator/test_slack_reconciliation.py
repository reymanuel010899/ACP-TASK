from services.action_broker.reconciliation import SlackReconciler
from agents.orchestrator.workflow_repository import WorkflowRepository


class Gateway:
    def __init__(self, result):
        self.result = result

    def find_effect(self, **kwargs):
        return dict(self.result)


def _attempt():
    return {
        "connection_id": "conn:1", "channel_id": "C1",
        "capability_id": "slack.message.send", "approved_payload_hash": "a" * 64,
        "dispatch_started_at": 100, "dispatch_ended_at": 110,
    }


def test_found_effect_completes_without_second_write():
    result = SlackReconciler(Gateway({
        "outcome": "found", "provider_id": "123.45",
    })).reconcile(_attempt())
    assert result == {
        "execution_status": "completed",
        "verification_status": "pending",
        "provider_id": "123.45",
        "retry_safe": False,
    }


def test_only_proven_absence_across_full_interval_is_retryable():
    proven = SlackReconciler(Gateway({
        "outcome": "absent", "complete_interval": True,
    })).reconcile(_attempt())
    incomplete = SlackReconciler(Gateway({
        "outcome": "absent", "complete_interval": False,
    })).reconcile(_attempt())
    assert proven["execution_status"] == "queued"
    assert proven["retry_safe"] is True
    assert incomplete["execution_status"] == "execution_unknown"
    assert incomplete["retry_safe"] is False


def test_unknown_write_cannot_retry_until_reconciliation_proves_absence(tmp_path):
    repository = WorkflowRepository(str(tmp_path / "w.db"))
    run = repository.create_run("org:1", "user:1", "goal", 1)
    revision = repository.create_revision(run["workflow_run_id"], "org:1", "graph", [{
        "step_id": "send", "capability_id": "slack.message.send",
        "capability_version": "1", "connection_id": "conn:1",
        "descriptor_snapshot_hash": "d", "input_hash": "i", "input": {},
        "depends_on": [], "effect": "write",
    }], 2)
    repository.record_approval(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:1", "graph", "user:1", 3,
    )
    claim = repository.claim_ready_step(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:1", "worker", 4, 60,
    )
    repository.mark_execution_unknown(
        revision["workflow_revision_id"], "send", "org:1", "timeout after dispatch"
    )
    assert repository.retry_safe_write(
        revision["workflow_revision_id"], "send", "org:1", claim["attempt"]
    ) is False
    repository.apply_reconciliation(
        revision["workflow_revision_id"], "send", "org:1", claim["attempt"],
        {"execution_status": "queued", "verification_status": "pending"},
    )
    assert repository.retry_safe_write(
        revision["workflow_revision_id"], "send", "org:1", claim["attempt"]
    ) is True
