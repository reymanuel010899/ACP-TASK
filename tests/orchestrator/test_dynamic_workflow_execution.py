from agents.orchestrator.workflow_executor import RetryableStepError, WorkflowExecutor
from agents.orchestrator.workflow_repository import WorkflowRepository


def test_retry_resumes_without_repeating_completed_step(tmp_path):
    repo = WorkflowRepository(str(tmp_path / "workflow.sqlite"))
    run = repo.create_run("org:1", "user:1", "goal", 1)
    steps = [{"step_id": name, "capability_id": capability, "capability_version": "1",
              "connection_id": "conn:1", "descriptor_snapshot_hash": "d", "input_hash": "i",
              "input": {}, "depends_on": deps, "effect": "write"}
             for name, capability, deps in [("calendar", "calendar.create", []), ("email", "gmail.send", ["calendar"])]]
    revision = repo.create_revision(run["workflow_run_id"], "org:1", "graph", steps, 2)
    repo.record_approval(run["workflow_run_id"], revision["workflow_revision_id"], "org:1", "graph", "user:1", 3)
    calls = []
    now = [4]

    def dispatch(step, claim):
        calls.append(step["step_id"])
        if step["step_id"] == "email" and calls.count("email") == 1:
            raise RetryableStepError("rate limited", retry_after=1)
        return {"output": {"id": step["step_id"]}, "receipt": {"id": step["step_id"]},
                "attestation": {"attestation_id": "att:%s:%s" % (step["step_id"], claim["attempt"])}}

    executor = WorkflowExecutor(repo, dispatch, clock=lambda: now[0])
    assert executor.run_until_blocked(run["workflow_run_id"], revision["workflow_revision_id"], "org:1", "worker")["status"] == "retry_wait"
    now[0] = 5
    assert executor.run_until_blocked(run["workflow_run_id"], revision["workflow_revision_id"], "org:1", "worker")["status"] == "complete"
    assert calls == ["calendar", "email", "email"]


def test_missing_output_reference_pauses_for_replan_and_revokes_claim(tmp_path):
    repo = WorkflowRepository(str(tmp_path / "workflow.sqlite"))
    run = repo.create_run("org:1", "user:1", "goal", 1)
    revision = repo.create_revision(run["workflow_run_id"], "org:1", "graph", [
        {"step_id": "lookup", "capability_id": "slack.search", "capability_version": "1",
         "connection_id": "conn:1", "descriptor_snapshot_hash": "d", "input_hash": "i",
         "input": {}, "depends_on": [], "effect": "read"},
        {"step_id": "send", "capability_id": "gmail.send", "capability_version": "1",
         "connection_id": "conn:2", "descriptor_snapshot_hash": "d", "input_hash": "i",
         "input": {"body": {"$ref": "lookup.output.missing"}},
         "depends_on": ["lookup"], "effect": "write"},
    ], 2)
    repo.record_approval(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:1", "graph", "user:1", 3,
    )

    def dispatch(step, claim):
        return {"output": {"found": "value"}, "receipt": {"id": "one"},
                "attestation": None}

    result = WorkflowExecutor(repo, dispatch, clock=lambda: 4).run_until_blocked(
        run["workflow_run_id"], revision["workflow_revision_id"], "org:1", "worker"
    )

    assert result == {"status": "needs_replan", "step_id": "send"}
    fetched = repo.get_revision(
        run["workflow_run_id"], revision["workflow_revision_id"], "org:1"
    )
    assert fetched["steps"][1]["execution_status"] == "paused_by_policy"


def test_requested_read_executes_without_explicit_write_approval(tmp_path):
    repo = WorkflowRepository(str(tmp_path / "workflow.sqlite"))
    run = repo.create_run("org:1", "user:1", "goal", 1)
    revision = repo.create_revision(run["workflow_run_id"], "org:1", "graph", [{
        "step_id": "read", "capability_id": "slack.conversation.read",
        "capability_version": "1", "connection_id": "conn:1",
        "descriptor_snapshot_hash": "d", "input_hash": "i",
        "input": {"oldest": "seven-days-ago"}, "depends_on": [], "effect": "read",
    }], 2)
    repo.authorize_requested_read(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:1", "graph", "user:1", 3,
    )
    calls = []
    def dispatch(step, claim):
        calls.append(step["input"])
        return {"receipt": {"messages": []}, "output": {"messages": []}}
    result = WorkflowExecutor(repo, dispatch, clock=lambda: 4).run_until_blocked(
        run["workflow_run_id"], revision["workflow_revision_id"], "org:1", "worker"
    )
    assert result["status"] == "complete"
    assert calls == [{"oldest": "seven-days-ago"}]
    assert not repo.is_revision_approved(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:1", "graph", 4,
    )
