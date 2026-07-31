from agents.orchestrator.workflow_executor import WorkflowExecutor
from agents.orchestrator.workflow_repository import WorkflowRepository
from agents.orchestrator.conversation_state import ConciergeConversationStore


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


def test_concierge_restart_preserves_tenant_bound_conversation_without_client_history(tmp_path):
    database = str(tmp_path / "workflow.sqlite3")
    repository = WorkflowRepository(database)
    store = ConciergeConversationStore(repository, clock=lambda: 10)
    store.create("org:acme", "user:alice", "conversation:restart")
    store.update(
        "conversation:restart", "org:acme", "user:alice",
        active_connection={"id": "conn:s", "label": "Acme"},
        active_channel={"id": "C1", "name": "general"},
        active_thread={"channel_id": "C1", "thread_ts": "1.0"},
        status="needs_input",
    )
    repository.close()

    restarted_repository = WorkflowRepository(database)
    restarted_store = ConciergeConversationStore(
        restarted_repository, clock=lambda: 11
    )
    recovered = restarted_store.get(
        "conversation:restart", "org:acme", "user:alice"
    )

    assert recovered["active_channel"] == {"id": "C1", "name": "general"}
    assert recovered["active_thread"] == {"channel_id": "C1", "thread_ts": "1.0"}
    assert restarted_store.get(
        "conversation:restart", "org:other", "user:alice"
    ) is None
