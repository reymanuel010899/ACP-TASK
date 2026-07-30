from agents.orchestrator.planner import PlanCompiler, descriptor_hash
from agents.orchestrator.workflow_executor import WorkflowExecutor
from agents.orchestrator.workflow_repository import WorkflowRepository
from libs.integrations.catalog import ConnectionCapabilitySnapshot, google_definitions, slack_definitions


def test_live_catalog_composes_slack_summary_into_approved_gmail_effect(tmp_path):
    slack = next(item for item in slack_definitions() if item.capability_id == "slack.thread.read")
    gmail = next(item for item in google_definitions() if item.capability_id == "gmail.send")
    snapshots = [
        ConnectionCapabilitySnapshot("conn:s", "org:acme", slack.capability_id, slack.version, 1, slack.required_scopes, "healthy", "r1"),
        ConnectionCapabilitySnapshot("conn:g", "org:acme", gmail.capability_id, gmail.version, 1, gmail.required_scopes, "healthy", "r1"),
    ]
    compiled = PlanCompiler([slack, gmail], snapshots, "r1").compile({
        "tenant_id": "org:acme", "goal": "Send Laura the Slack summary", "steps": [
            {"step_id": "read", "capability_id": slack.capability_id, "capability_version": slack.version, "connection_id": "conn:s", "descriptor_snapshot_hash": descriptor_hash(slack), "depends_on": [], "input": {"channel_id": "C1", "thread_ts": "1.2"}},
            {"step_id": "email", "capability_id": gmail.capability_id, "capability_version": gmail.version, "connection_id": "conn:g", "descriptor_snapshot_hash": descriptor_hash(gmail), "depends_on": ["read"], "input": {"to": "laura@example.com", "subject": "Resumen", "body": {"$ref": "read.output.summary"}}},
        ],
    })
    repository = WorkflowRepository(str(tmp_path / "workflow.sqlite3"))
    run = repository.create_run("org:acme", "user:alice", "goal", 1)
    revision = repository.create_revision(run["workflow_run_id"], "org:acme", compiled["plan_graph_hash"], [dict(step, input_hash="hash") for step in compiled["steps"]], 2)
    repository.record_approval(run["workflow_run_id"], revision["workflow_revision_id"], "org:acme", compiled["plan_graph_hash"], "user:alice", 3)
    dispatched = []

    def dispatch(step, claim):
        dispatched.append((step["step_id"], step["input"]))
        if step["step_id"] == "read":
            return {"output": {"summary": "Entrevista mañana"}, "receipt": {"summary": "Entrevista mañana"}}
        return {"output": {"id": "msg-1"}, "receipt": {"id": "msg-1"}, "attestation": {"attestation_id": "att:%s" % claim["attempt"]}}

    result = WorkflowExecutor(repository, dispatch, clock=lambda: 4).run_until_blocked(run["workflow_run_id"], revision["workflow_revision_id"], "org:acme", "worker")
    assert result["status"] == "complete"
    assert dispatched[1][1] == {"to": "laura@example.com", "subject": "Resumen", "body": "Entrevista mañana"}
