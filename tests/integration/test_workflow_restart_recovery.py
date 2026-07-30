from agents.orchestrator.workflow_executor import WorkflowExecutor
from agents.orchestrator.workflow_repository import WorkflowRepository


def test_restart_continues_after_completed_step_without_repeating_it(tmp_path):
    database = str(tmp_path / "workflow.sqlite3")
    repository = WorkflowRepository(database)
    run = repository.create_run("org:acme", "user:alice", "goal", 1)
    steps = [
        {"step_id": "one", "capability_id": "slack.channels.list", "capability_version": "1", "connection_id": "conn:s", "descriptor_snapshot_hash": "d", "input_hash": "i", "input": {}, "depends_on": [], "effect": "read"},
        {"step_id": "two", "capability_id": "slack.conversation.read", "capability_version": "1", "connection_id": "conn:s", "descriptor_snapshot_hash": "d", "input_hash": "i", "input": {}, "depends_on": ["one"], "effect": "read"},
    ]
    revision = repository.create_revision(run["workflow_run_id"], "org:acme", "graph", steps, 2)
    repository.record_approval(run["workflow_run_id"], revision["workflow_revision_id"], "org:acme", "graph", "user:alice", 3)
    claim = repository.claim_ready_step(run["workflow_run_id"], revision["workflow_revision_id"], "org:acme", "worker-1", 4, 60)
    repository.persist_completion(revision["workflow_revision_id"], "one", "org:acme", claim["attempt"], {"id": "one"}, None, 4, output={"id": "one"})
    repository.close()

    calls = []
    restarted = WorkflowRepository(database)
    result = WorkflowExecutor(restarted, lambda step, _claim: calls.append(step["step_id"]) or {"receipt": {"id": step["step_id"]}, "output": {"id": step["step_id"]}}, clock=lambda: 5).run_until_blocked(run["workflow_run_id"], revision["workflow_revision_id"], "org:acme", "worker-2")
    assert result["status"] == "complete"
    assert calls == ["two"]
