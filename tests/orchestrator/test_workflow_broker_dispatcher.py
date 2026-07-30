from agents.orchestrator.action_repository import ActionRepository
from agents.orchestrator.workflow_broker_dispatcher import (
    WorkflowBrokerDispatcher,
    _matches_approved_template,
)
from agents.orchestrator.workflow_repository import WorkflowRepository


def test_group_approval_materializes_one_exact_action_and_lease(tmp_path):
    workflows = WorkflowRepository(str(tmp_path / "w.db")); actions = ActionRepository(str(tmp_path / "a.db"))
    run = workflows.create_run("org:1", "user:1", "goal", 1)
    revision = workflows.create_revision(run["workflow_run_id"], "org:1", "graph", [{
        "step_id": "send", "capability_id": "slack.message.send", "capability_version": "1.0.0",
        "connection_id": "conn:1", "descriptor_snapshot_hash": "d", "input_hash": "i",
        "input": {"channel_id": "C1", "text": "hello"}, "depends_on": [], "effect": "write",
    }], 2)
    workflows.record_approval(run["workflow_run_id"], revision["workflow_revision_id"], "org:1", "graph", "user:1", 3)
    claim = workflows.claim_ready_step(run["workflow_run_id"], revision["workflow_revision_id"], "org:1", "worker", 4, 60)
    step = workflows.get_revision(run["workflow_run_id"], revision["workflow_revision_id"], "org:1")["steps"][0]
    class Connections:
        def get_installation(self, connection_id, tenant_id):
            return {"connection_id": connection_id, "status": "connected", "credential_id": "cred:1", "credential_version": 1,
                    "granted_scopes": ["chat:write"], "team_id": "T1", "bot_user_id": "B1"}
    class Broker:
        def execute(self, lease, binding, payload):
            assert actions.validate_lease(lease, binding, 5)
            assert binding["payload_hash"]
            assert binding["workflow_revision_id"] == revision["workflow_revision_id"]
            assert binding["step_id"] == "send"
            assert binding["plan_graph_hash"] == "graph"
            assert binding["attempt"] == 1
            tampered = dict(binding, attempt=2)
            assert not actions.validate_lease(lease, tampered, 5)
            return 200, {"receipt": {"channel_id": "C1", "message_ts": "1.2"},
                         "execution_attestation": {"attestation_id": "att:1"}}
    result = WorkflowBrokerDispatcher(actions, Broker(), Connections(), workflows, clock=lambda: 5)(step, claim)
    assert result["receipt"]["message_ts"] == "1.2"
    assert actions.get("proposal:%s:%s" % (revision["workflow_revision_id"], "send"))["status"] == "approved"


def test_dynamic_approval_rejects_a_changed_attempt(tmp_path):
    actions = ActionRepository(str(tmp_path / "actions.sqlite3"))
    proposal = actions.create_proposal(
        "user:1", "agent:orchestrator", "cred:1", "slack.message.send",
        {"channel_id": "C1", "text": "hello"}, 100,
        workflow_revision_id="revision:1", step_id="send",
        plan_graph_hash="graph:1", connection_id="conn:1", attempt=1,
    )
    assert actions.decide(proposal["proposal_id"], proposal["version"], "user:1", True, 1)
    binding = {
        "proposal_id": proposal["proposal_id"], "version": proposal["version"],
        "user_principal_id": "user:1", "agent_principal_id": "agent:orchestrator",
        "credential_id": "cred:1", "capability_id": "slack.message.send",
        "payload_hash": proposal["payload_hash"],
        "idempotency_key": proposal["idempotency_key"],
        "workflow_revision_id": "revision:1", "step_id": "send",
        "plan_graph_hash": "graph:1", "connection_id": "conn:1", "attempt": 2,
    }

    assert actions.consume_approval(binding, 2) is None
    binding["attempt"] = 1
    assert actions.consume_approval(binding, 2)["status"] == "executing"


def test_read_binding_matches_its_workflow_capability_lease(tmp_path):
    workflows = WorkflowRepository(str(tmp_path / "w.db"))
    actions = ActionRepository(str(tmp_path / "a.db"))
    run = workflows.create_run("org:1", "user:1", "goal", 1)
    revision = workflows.create_revision(run["workflow_run_id"], "org:1", "graph", [{
        "step_id": "channels", "capability_id": "slack.channels.list",
        "capability_version": "1.0.0", "connection_id": "conn:1",
        "descriptor_snapshot_hash": "d", "input_hash": "i", "input": {},
        "depends_on": [], "effect": "read",
    }], 2)
    workflows.record_approval(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:1", "graph", "user:1", 3,
    )
    claim = workflows.claim_ready_step(
        run["workflow_run_id"], revision["workflow_revision_id"],
        "org:1", "worker", 4, 60,
    )
    step = workflows.get_revision(
        run["workflow_run_id"], revision["workflow_revision_id"], "org:1"
    )["steps"][0]

    class Connections:
        def get_installation(self, connection_id, tenant_id):
            return {
                "connection_id": connection_id, "status": "connected",
                "credential_id": "cred:1", "credential_version": 1,
                "granted_scopes": ["channels:read"], "team_id": "T1",
                "bot_user_id": "B1",
            }

    class Broker:
        def execute(self, lease, binding, payload):
            assert actions.validate_lease(lease, binding, 5)
            assert binding["workflow_revision_id"] == revision["workflow_revision_id"]
            assert binding["step_id"] == "channels"
            assert binding["plan_graph_hash"] == "graph"
            assert binding["attempt"] == 1
            return 200, {"receipt": {"channels": []}}

    result = WorkflowBrokerDispatcher(
        actions, Broker(), Connections(), workflows, clock=lambda: 5
    )(step, claim)

    assert result["output"] == {"channels": []}


def test_resolved_effect_may_change_only_declared_references():
    approved = {
        "to": "laura@example.com",
        "subject": "Resumen",
        "body": {"$ref": "search.output.summary"},
    }
    assert _matches_approved_template(approved, {
        "to": "laura@example.com", "subject": "Resumen", "body": "Contenido",
    })
    assert not _matches_approved_template(approved, {
        "to": "attacker@example.com", "subject": "Resumen", "body": "Contenido",
    })
