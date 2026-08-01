from agents.orchestrator.workflow_executor import WorkflowExecutor
from agents.orchestrator.workflow_repository import WorkflowRepository
from agents.orchestrator.conversation_state import ConciergeConversationStore
from services.workflow_worker.app import WorkflowWorker


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


def test_worker_terminal_projection_updates_the_durable_conversation(tmp_path):
    repository = WorkflowRepository(str(tmp_path / "workflow.sqlite3"))
    store = ConciergeConversationStore(repository, clock=lambda: 10)
    conversation = store.create("org:acme", "user:alice", "conversation:worker")
    run = repository.create_run("org:acme", "user:alice", "goal", 10)
    revision = repository.create_revision(run["workflow_run_id"], "org:acme", "graph", [{
        "step_id": "send", "capability_id": "slack.message.send",
        "capability_version": "1", "connection_id": "conn:s",
        "descriptor_snapshot_hash": "d", "input_hash": "i",
        "input": {"channel_id": "C1", "text": "Hola"},
        "depends_on": [], "effect": "write",
    }], 10)
    store.update(
        conversation["conversation_id"], "org:acme", "user:alice",
        status="executing", pending_draft={"text": "Hola"},
        workflow_run_id=run["workflow_run_id"],
        workflow_revision_id=revision["workflow_revision_id"],
    )

    assert repository.sync_conversation_workflow_outcome(
        revision["workflow_revision_id"], "org:acme", {"status": "complete"}, 11
    )
    completed = store.get("conversation:worker", "org:acme", "user:alice")
    assert completed["status"] == "succeeded"
    assert completed.get("pending_draft") is None
    assert completed["presentation"]["answer"] == "Mensaje enviado"


def test_worker_restart_enqueues_completed_linked_revision_once(tmp_path, monkeypatch):
    monkeypatch.setattr("services.workflow_worker.app.time.time", lambda: 12)
    database = str(tmp_path / "workflow.sqlite3")
    repository = WorkflowRepository(database)
    store = ConciergeConversationStore(repository, clock=lambda: 10)
    conversation = store.create("org:acme", "user:alice", "conversation:outbox")
    run = repository.create_run("org:acme", "user:alice", "goal", 10)
    revision = repository.create_revision(run["workflow_run_id"], "org:acme", "graph", [{
        "step_id": "read", "capability_id": "slack.channels.list",
        "capability_version": "1", "connection_id": "conn:s",
        "descriptor_snapshot_hash": "d", "input_hash": "i", "input": {},
        "depends_on": [], "effect": "read",
    }], 10)
    repository.authorize_requested_read(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:acme", "graph", "user:alice", 10,
    )
    store.update(
        conversation["conversation_id"], "org:acme", "user:alice",
        status="executing", workflow_run_id=run["workflow_run_id"],
        workflow_revision_id=revision["workflow_revision_id"],
    )
    claim = repository.claim_ready_step(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:acme", "worker:crashed", 11, 60,
    )
    repository.persist_completion(
        revision["workflow_revision_id"], "read", "org:acme",
        claim["attempt"], {"provider_id": "read:1"}, None, 11,
        output={"channels": [{"id": "C1", "name": "general"}]},
    )
    repository.close()

    restarted = WorkflowRepository(database)
    worker = WorkflowWorker(restarted, object(), "worker:restarted")
    worker.run_once()
    worker.run_once()

    projected = ConciergeConversationStore(restarted, clock=lambda: 12).get(
        "conversation:outbox", "org:acme", "user:alice"
    )
    assert projected["status"] == "ready"
    assert projected["presentation"]["answer"] == "Tienes 1 canales públicos: #general"
    assert restarted.count_outbox_events(
        "org:acme", "revision:%s:complete" % revision["workflow_revision_id"]
    ) == 1
