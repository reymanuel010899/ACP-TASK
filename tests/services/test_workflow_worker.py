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
