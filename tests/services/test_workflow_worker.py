from services.workflow_worker.app import WorkflowWorker


def test_worker_runs_each_approved_revision():
    class Repository:
        def list_approved_revisions(self):
            return [{"workflow_run_id": "w", "workflow_revision_id": "r", "tenant_id": "t"}]
    calls = []
    class Executor:
        def run_until_blocked(self, *args):
            calls.append(args); return {"status": "complete"}
    assert WorkflowWorker(Repository(), Executor(), "worker:1").run_once() == [{"status": "complete"}]
    assert calls == [("w", "r", "t", "worker:1")]


def test_worker_schedules_requested_reads_but_not_unapproved_writes():
    class Repository:
        def list_runnable_revisions(self):
            return [{
                "workflow_run_id": "read-run", "workflow_revision_id": "read-rev",
                "tenant_id": "org:1", "authorization_mode": "requested_read",
            }]
    calls = []
    class Executor:
        def run_until_blocked(self, *args):
            calls.append(args); return {"status": "complete"}
    assert WorkflowWorker(Repository(), Executor(), "worker:1").run_once() == [{"status": "complete"}]
    assert calls == [("read-run", "read-rev", "org:1", "worker:1")]


def test_worker_enqueues_then_projects_terminal_outcome():
    class Repository:
        events = []
        def list_runnable_revisions(self):
            return [{"workflow_run_id": "w", "workflow_revision_id": "r",
                     "tenant_id": "org:1"}]
        def recover_unprojected_conversation_outcomes(self, now):
            return 0
        def enqueue_workflow_conversation_outcome(self, revision, tenant, outcome, now):
            self.events.append({
                "event_id": "event:1", "tenant_id": tenant,
                "aggregate_type": "conversation", "aggregate_id": "conversation:1",
                "aggregate_version": 1, "event_type": "workflow.outcome",
                "payload": {"revision_id": revision, "outcome": outcome},
            })
        def claim_outbox_event(self, worker, now, visibility):
            return self.events.pop(0) if self.events else None
        def sync_conversation_workflow_outcome(self, revision, tenant, outcome, now):
            self.synced = (revision, tenant, outcome)
            return True
        def advance_projection_watermark(self, tenant, kind, aggregate, version, event, now):
            self.watermark = (tenant, kind, aggregate, version, event)
            return True
        def complete_outbox_event(self, event, tenant, worker, now):
            self.completed = (event, tenant, worker)
            return True
    repository = Repository()
    class Executor:
        def run_until_blocked(self, *args):
            return {"status": "execution_unknown", "step_id": "send"}
    WorkflowWorker(repository, Executor(), "worker:1").run_once()
    assert repository.synced == (
        "r", "org:1", {"status": "execution_unknown", "step_id": "send"}
    )
    assert repository.watermark[:4] == (
        "org:1", "conversation", "conversation:1", 1
    )
    assert repository.completed == ("event:1", "org:1", "worker:1")


def test_worker_acknowledges_committed_turn_event_without_mutating_conversation():
    class Repository:
        def __init__(self):
            self.event = {
                "event_id": "event:turn", "tenant_id": "org:1",
                "aggregate_type": "conversation",
                "aggregate_id": "conversation:1", "aggregate_version": 2,
                "event_type": "conversation.turn_committed",
                "payload": {"client_turn_id": "turn:1", "state_version": 2},
            }

        def list_runnable_revisions(self):
            return []

        def claim_outbox_event(self, worker, now, visibility):
            event, self.event = self.event, None
            return event

        def sync_conversation_workflow_outcome(self, *args):
            raise AssertionError("turn event must not reapply conversation state")

        def advance_projection_watermark(
            self, tenant, kind, aggregate, version, event, now
        ):
            self.watermark = (tenant, kind, aggregate, version, event)
            return True

        def complete_outbox_event(self, event, tenant, worker, now):
            self.completed = (event, tenant, worker)
            return True

    repository = Repository()

    class Executor:
        pass

    WorkflowWorker(repository, Executor(), "worker:1").run_once()

    assert repository.watermark == (
        "org:1", "conversation", "conversation:1", 2, "event:turn"
    )
    assert repository.completed == ("event:turn", "org:1", "worker:1")


class _ResolverEventRepository:
    def __init__(self, resumable=()):
        self.event = {
            "event_id": "event:resolver", "tenant_id": "org:1",
            "aggregate_type": "conversation",
            "aggregate_id": "conversation:1", "aggregate_version": 3,
            "event_type": "conversation.resolver_completed",
            "payload": {
                "resolver_run_id": "slack-resolver:1",
                "principal_id": "user:1", "outcome": "matched",
            },
        }
        self.resumable = list(resumable)

    def list_runnable_revisions(self):
        return []

    def claim_outbox_event(self, worker, now, visibility):
        event, self.event = self.event, None
        return event

    def sync_conversation_workflow_outcome(self, *args):
        raise AssertionError("resolver events must not replay workflow outcomes")

    def advance_projection_watermark(self, tenant, kind, aggregate, version,
                                     event, now):
        self.watermark = (tenant, kind, aggregate, version, event)
        return True

    def complete_outbox_event(self, event, tenant, worker, now):
        self.completed = (event, tenant, worker)
        return True

    def list_resumable_slack_resolver_runs(self, now):
        return self.resumable


def test_worker_completes_resolution_from_its_durable_event():
    repository = _ResolverEventRepository()
    applied = []

    class Resolver:
        def apply_slack_resolver_completion(self, tenant, conversation,
                                            payload, now):
            applied.append((tenant, conversation, payload["resolver_run_id"]))
            return True

        def continue_slack_resolver_run(self, run, now):
            raise AssertionError("a completed run must not be paged again")

    class Executor:
        pass

    WorkflowWorker(
        repository, Executor(), "worker:1", conversation_resolver=Resolver()
    ).run_once()

    assert applied == [("org:1", "conversation:1", "slack-resolver:1")]
    assert repository.watermark == (
        "org:1", "conversation", "conversation:1", 3, "event:resolver"
    )
    assert repository.completed == ("event:resolver", "org:1", "worker:1")


def test_worker_pages_resumable_resolver_runs_and_survives_one_failure():
    runs = [
        {"resolver_run_id": "slack-resolver:broken"},
        {"resolver_run_id": "slack-resolver:2"},
    ]
    repository = _ResolverEventRepository(resumable=runs)
    continued = []

    class Resolver:
        def apply_slack_resolver_completion(self, *args):
            return True

        def continue_slack_resolver_run(self, run, now):
            if run["resolver_run_id"].endswith("broken"):
                raise RuntimeError("transient dispatch failure")
            continued.append(run["resolver_run_id"])
            return True

    class Executor:
        pass

    WorkflowWorker(
        repository, Executor(), "worker:1", conversation_resolver=Resolver()
    ).run_once()

    assert continued == ["slack-resolver:2"]


def test_worker_without_a_resolver_still_acknowledges_resolution_events():
    repository = _ResolverEventRepository(resumable=[{"resolver_run_id": "x"}])

    class Executor:
        pass

    WorkflowWorker(repository, Executor(), "worker:1").run_once()

    assert repository.completed == ("event:resolver", "org:1", "worker:1")
