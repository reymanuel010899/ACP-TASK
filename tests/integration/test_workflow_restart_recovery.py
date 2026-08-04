import pytest

from agents.orchestrator.action_repository import ActionRepository
from agents.orchestrator.reconciliation import WorkflowReconciler
from agents.orchestrator.workflow_broker_dispatcher import WorkflowBrokerDispatcher
from agents.orchestrator.workflow_executor import WorkflowExecutor
from agents.orchestrator.workflow_repository import WorkflowRepository
from agents.orchestrator.conversation_state import ConciergeConversationStore
from services.action_broker.reconciliation import SlackReconciler
from services.workflow_worker.app import WorkflowWorker


class FakeSlack:
    """One Slack workspace: it counts creates and can be asked what it holds."""

    def __init__(self):
        self.created = []
        self.lookups = 0

    def create(self, text):
        self.created.append(text)
        return {"provider": "slack", "channel_id": "C1",
                "provider_id": "1700.%s" % len(self.created),
                "message_ts": "1700.%s" % len(self.created)}

    def find_effect(self, **_criteria):
        self.lookups += 1
        if not self.created:
            return {"outcome": "absent", "complete_interval": True}
        receipt = {"provider": "slack", "channel_id": "C1",
                   "provider_id": "1700.1", "message_ts": "1700.1"}
        return {"outcome": "found", "provider_id": "1700.1",
                "receipt": receipt,
                "attestation": {"attestation_id": "att:reconciled",
                                "provider_receipt": receipt}}


class UnreachableSlack(FakeSlack):
    def find_effect(self, **_criteria):
        self.lookups += 1
        raise ConnectionError("slack is unreachable")


class RecordingBroker:
    """A broker that moves the proposal exactly as the real one does."""

    def __init__(self, actions, provider, now, lose_response=False):
        self.actions = actions
        self.provider = provider
        self.now = now
        self.lose_response = lose_response

    def execute(self, lease, binding, payload):
        self.actions.consume_approval(binding, self.now)
        self.actions.mark_dispatched(
            binding["proposal_id"], binding["version"], self.now,
        )
        receipt = self.provider.create(payload["text"])
        if self.lose_response:
            self.actions.fail_execution(
                binding["proposal_id"], binding["version"],
                "timeout after dispatch", self.now, unknown=True,
            )
            return 202, {"status": "execution_unknown"}
        self.actions.complete_execution(
            binding["proposal_id"], binding["version"], receipt, self.now,
        )
        return 200, {"receipt": receipt,
                     "execution_attestation": {"attestation_id": "att:1",
                                               "provider_receipt": receipt}}


class Connections:
    def get_installation(self, connection_id, tenant_id):
        return {"connection_id": connection_id, "status": "connected",
                "credential_id": "cred:1", "credential_version": 1,
                "granted_scopes": ["chat:write"], "team_id": "T1",
                "bot_user_id": "B1"}


def _write_workflow(repository, tenant="org:acme"):
    run = repository.create_run(tenant, "user:alice", "goal", 1)
    revision = repository.create_revision(run["workflow_run_id"], tenant, "graph", [{
        "step_id": "send", "capability_id": "slack.message.send",
        "capability_version": "1.0.0", "connection_id": "conn:s",
        "descriptor_snapshot_hash": "d", "input_hash": "i",
        "input": {"channel_id": "C1", "text": "Hola"},
        "depends_on": [], "effect": "write",
    }], 2)
    repository.record_approval(
        run["workflow_run_id"], revision["workflow_revision_id"], tenant,
        "graph", "user:alice", 3, ttl_seconds=10 ** 6,
    )
    return run, revision


def _executor(workflows, actions, broker, now):
    return WorkflowExecutor(
        workflows,
        WorkflowBrokerDispatcher(
            actions, broker, Connections(), workflows, clock=lambda: now,
        ),
        clock=lambda: now,
    )


def test_a_confirmed_unknown_write_reconciles_to_completed_with_one_provider_create(
    tmp_path,
):
    """An unknown outcome is a question for the provider, not a dead end."""
    workflows = WorkflowRepository(str(tmp_path / "w.db"))
    actions = ActionRepository(str(tmp_path / "a.db"))
    run, revision = _write_workflow(workflows)
    revision_id = revision["workflow_revision_id"]
    slack = FakeSlack()

    dispatched = _executor(
        workflows, actions, RecordingBroker(actions, slack, 10, lose_response=True), 10,
    ).run_next(run["workflow_run_id"], revision_id, "org:acme", "worker-1")
    assert dispatched["status"] == "execution_unknown"

    verdicts = WorkflowReconciler(
        workflows, actions, {"slack": SlackReconciler(slack)},
    ).run_once(20)

    assert [verdict["status"] for verdict in verdicts] == ["completed"]
    step = workflows.get_revision(
        run["workflow_run_id"], revision_id, "org:acme"
    )["steps"][0]
    assert step["execution_status"] == "completed"
    assert workflows.get_step_receipt(
        revision_id, "send", "org:acme"
    )["provider_id"] == "1700.1"
    assert actions.get("proposal:%s:send" % revision_id)["status"] == "completed"
    assert slack.created == ["Hola"]


def test_unreachable_reconciliation_keeps_the_effect_unknown_and_blocked(tmp_path):
    """Not knowing is a state to escalate, never a licence to send again."""
    workflows = WorkflowRepository(str(tmp_path / "w.db"))
    actions = ActionRepository(str(tmp_path / "a.db"))
    run, revision = _write_workflow(workflows)
    revision_id = revision["workflow_revision_id"]
    slack = UnreachableSlack()

    _executor(
        workflows, actions, RecordingBroker(actions, slack, 10, lose_response=True), 10,
    ).run_next(run["workflow_run_id"], revision_id, "org:acme", "worker-1")

    verdict = WorkflowReconciler(
        workflows, actions, {"slack": SlackReconciler(slack)}, retry_seconds=30,
    ).run_once(20)[0]

    assert verdict["status"] == "execution_unknown"
    assert verdict["requires_resolution"] is True
    current = workflows.get_revision(
        run["workflow_run_id"], revision_id, "org:acme"
    )
    assert current["steps"][0]["execution_status"] == "execution_unknown"
    # The human-resolvable item, and the block on any new attempt.
    assert WorkflowRepository.recovery_options(current)["unknownStepIds"] == ["send"]
    assert workflows.retry_safe_write(
        revision_id, "send", "org:acme", current["steps"][0]["attempt"],
    ) is False
    # The dispatch that went unanswered, and nothing after it.
    assert slack.created == ["Hola"]


def test_repeated_unreachable_reconciliation_escalates_to_a_human(tmp_path):
    workflows = WorkflowRepository(str(tmp_path / "w.db"))
    actions = ActionRepository(str(tmp_path / "a.db"))
    run, revision = _write_workflow(workflows)
    revision_id = revision["workflow_revision_id"]
    slack = UnreachableSlack()

    _executor(
        workflows, actions, RecordingBroker(actions, slack, 10, lose_response=True), 10,
    ).run_next(run["workflow_run_id"], revision_id, "org:acme", "worker-1")
    reconciler = WorkflowReconciler(
        workflows, actions, {"slack": SlackReconciler(slack)},
        retry_seconds=10, max_attempts=3,
    )

    verdicts = [reconciler.run_once(20 + tick * 20)[0] for tick in range(3)]

    assert [verdict["exhausted"] for verdict in verdicts] == [False, False, True]
    step = workflows.get_revision(
        run["workflow_run_id"], revision_id, "org:acme"
    )["steps"][0]
    assert step["execution_status"] == "execution_unknown"
    assert step["terminal_reason"].startswith("awaiting human resolution")


def test_two_worker_ticks_on_one_unknown_outcome_produce_one_verdict(tmp_path):
    workflows = WorkflowRepository(str(tmp_path / "w.db"))
    actions = ActionRepository(str(tmp_path / "a.db"))
    run, revision = _write_workflow(workflows)
    revision_id = revision["workflow_revision_id"]
    slack = FakeSlack()

    _executor(
        workflows, actions, RecordingBroker(actions, slack, 10, lose_response=True), 10,
    ).run_next(run["workflow_run_id"], revision_id, "org:acme", "worker-1")

    pending = workflows.list_unresolved_write_steps(20)
    assert len(pending) == 1
    first = WorkflowReconciler(
        workflows, actions, {"slack": SlackReconciler(slack)}, worker_id="w1",
    ).reconcile(pending[0], 20)
    second = WorkflowReconciler(
        workflows, actions, {"slack": SlackReconciler(slack)}, worker_id="w2",
    ).reconcile(pending[0], 20)

    assert first["status"] == "completed"
    assert second is None
    assert slack.lookups == 1
    assert slack.created == ["Hola"]


@pytest.mark.parametrize("stop_after", ["claim", "provider_receipt", "projection"])
def test_a_worker_restart_never_duplicates_an_effect(tmp_path, stop_after):
    database = str(tmp_path / "workflow.sqlite3")
    workflows = WorkflowRepository(database)
    actions = ActionRepository(str(tmp_path / "a.db"))
    run, revision = _write_workflow(workflows)
    revision_id = revision["workflow_revision_id"]
    slack = FakeSlack()

    if stop_after == "claim":
        workflows.claim_ready_step(
            run["workflow_run_id"], revision_id, "org:acme", "worker:crashed", 10, 60,
        )
    else:
        _executor(
            workflows, actions,
            RecordingBroker(actions, slack, 10,
                            lose_response=stop_after == "provider_receipt"),
            10,
        ).run_next(run["workflow_run_id"], revision_id, "org:acme", "worker:crashed")
    workflows.close()

    restarted = WorkflowRepository(database)
    restarted.recover_expired_claims(200)
    WorkflowReconciler(
        restarted, actions, {"slack": SlackReconciler(slack)},
    ).run_once(200)
    result = _executor(
        restarted, actions, RecordingBroker(actions, slack, 210), 210,
    ).run_until_blocked(run["workflow_run_id"], revision_id, "org:acme", "worker:new")

    assert result["status"] == "complete"
    assert slack.created == ["Hola"]
    assert restarted.get_revision(
        run["workflow_run_id"], revision_id, "org:acme"
    )["steps"][0]["execution_status"] == "completed"


def test_the_worker_tick_sweeps_and_reconciles_without_an_explicit_call(tmp_path,
                                                                       monkeypatch):
    """The machinery only helps if the tick actually runs it."""
    monkeypatch.setattr("services.workflow_worker.app.time.time", lambda: 500)
    workflows = WorkflowRepository(str(tmp_path / "w.db"))
    actions = ActionRepository(str(tmp_path / "a.db"))
    run, revision = _write_workflow(workflows)
    revision_id = revision["workflow_revision_id"]
    slack = FakeSlack()

    _executor(
        workflows, actions, RecordingBroker(actions, slack, 10, lose_response=True), 10,
    ).run_next(run["workflow_run_id"], revision_id, "org:acme", "worker-1")

    WorkflowWorker(
        workflows,
        _executor(workflows, actions, RecordingBroker(actions, slack, 500), 500),
        "worker:tick", actions=actions,
        reconciler=WorkflowReconciler(
            workflows, actions, {"slack": SlackReconciler(slack)},
        ),
    ).run_once()

    assert workflows.get_revision(
        run["workflow_run_id"], revision_id, "org:acme"
    )["steps"][0]["execution_status"] == "completed"
    assert slack.created == ["Hola"]


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
