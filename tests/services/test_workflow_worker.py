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


def test_worker_projects_terminal_outcome_to_linked_conversation():
    class Repository:
        def list_runnable_revisions(self):
            return [{"workflow_run_id": "w", "workflow_revision_id": "r",
                     "tenant_id": "org:1"}]
        def sync_conversation_workflow_outcome(self, revision, tenant, outcome, now):
            self.synced = (revision, tenant, outcome)
    repository = Repository()
    class Executor:
        def run_until_blocked(self, *args):
            return {"status": "execution_unknown", "step_id": "send"}
    WorkflowWorker(repository, Executor(), "worker:1").run_once()
    assert repository.synced == (
        "r", "org:1", {"status": "execution_unknown", "step_id": "send"}
    )
