import pytest

from agents.orchestrator.action_repository import ActionRepository
from agents.orchestrator.workflow_broker_dispatcher import (
    WorkflowBrokerDispatcher,
    _raise_for_broker_failure,
    _matches_approved_template,
)
from agents.orchestrator.workflow_repository import WorkflowRepository
from agents.orchestrator.workflow_executor import (
    AmbiguousStepError, CorrectableStepError, PausedStepError,
    RetryableStepError, WorkflowExecutor,
)


def _write_revision(workflows, tenant="org:1"):
    run = workflows.create_run(tenant, "user:1", "goal", 1)
    revision = workflows.create_revision(run["workflow_run_id"], tenant, "graph", [{
        "step_id": "send", "capability_id": "slack.message.send",
        "capability_version": "1.0.0", "connection_id": "conn:1",
        "descriptor_snapshot_hash": "d", "input_hash": "i",
        "input": {"channel_id": "C1", "text": "Hola"},
        "depends_on": [], "effect": "write",
    }], 2)
    workflows.record_approval(
        run["workflow_run_id"], revision["workflow_revision_id"], tenant,
        "graph", "user:1", 3, ttl_seconds=10 ** 6,
    )
    return run, revision


def _strand_prior_attempt(actions, revision_id):
    """Leave the step's proposal id unresolved, exactly as a timeout would."""
    common = {
        "user_principal_id": "user:1",
        "agent_principal_id": "agent:orchestrator",
        "credential_id": "cred:1", "capability_id": "slack.message.send",
        "payload": {"channel_id": "C1", "text": "Hola"}, "expires_at": 10_000,
        "proposal_id": "proposal:%s:send" % revision_id,
        "idempotency_key": "workflow:%s:send" % revision_id,
        "workflow_revision_id": revision_id, "step_id": "send",
        "plan_graph_hash": "graph", "connection_id": "conn:1",
    }
    prior = actions.create_proposal(attempt=1, **common)
    actions.decide(prior["proposal_id"], prior["version"], "user:1", True, 4)
    binding = {key: prior[key] for key in (
        "proposal_id", "version", "user_principal_id", "agent_principal_id",
        "credential_id", "capability_id", "payload_hash", "idempotency_key",
        "workflow_revision_id", "step_id", "plan_graph_hash", "connection_id",
        "attempt")}
    actions.consume_approval(binding, 4)
    actions.mark_dispatched(prior["proposal_id"], prior["version"], 4)
    actions.fail_execution(
        prior["proposal_id"], prior["version"], "timeout", 4, unknown=True,
    )
    return prior


class _Connections:
    def __init__(self, status="connected"):
        self.status = status

    def get_installation(self, connection_id, tenant_id):
        return {"connection_id": connection_id, "status": self.status,
                "credential_id": "cred:1", "credential_version": 1,
                "granted_scopes": ["chat:write"], "team_id": "T1",
                "bot_user_id": "B1"}


class _UnreachableBroker:
    def execute(self, *_args):
        raise AssertionError("provider must not be reached before dispatch")


def test_a_duplicate_prevention_refusal_is_reported_as_a_pre_dispatch_rejection(
    tmp_path,
):
    """A refusal that means "nothing was sent" must not become "we might have sent it"."""
    workflows = WorkflowRepository(str(tmp_path / "w.db"))
    actions = ActionRepository(str(tmp_path / "a.db"))
    run, revision = _write_revision(workflows)
    revision_id = revision["workflow_revision_id"]
    _strand_prior_attempt(actions, revision_id)

    dispatcher = WorkflowBrokerDispatcher(
        actions, _UnreachableBroker(), _Connections(), workflows, clock=lambda: 5,
    )
    result = WorkflowExecutor(workflows, dispatcher, clock=lambda: 5).run_next(
        run["workflow_run_id"], revision_id, "org:1", "worker",
    )

    assert result["status"] == "retryable_failure"
    assert result["recovery"] == "pre_dispatch:ValueError"
    step = workflows.get_revision(
        run["workflow_run_id"], revision_id, "org:1"
    )["steps"][0]
    assert step["execution_status"] != "execution_unknown"
    assert step["step_id"] not in WorkflowRepository.recovery_options(
        workflows.get_revision(run["workflow_run_id"], revision_id, "org:1")
    )["unknownStepIds"]


def test_an_unavailable_connection_waits_without_spending_retry_attempts(tmp_path):
    """A provider outage must not convert queued work into permanent failure."""
    workflows = WorkflowRepository(str(tmp_path / "w.db"))
    actions = ActionRepository(str(tmp_path / "a.db"))
    run, revision = _write_revision(workflows)
    revision_id = revision["workflow_revision_id"]
    clock = [5]
    executor = WorkflowExecutor(
        workflows,
        WorkflowBrokerDispatcher(
            actions, _UnreachableBroker(), _Connections("disconnected"),
            workflows, clock=lambda: clock[0],
        ),
        clock=lambda: clock[0],
    )

    for _outage_tick in range(8):
        assert executor.run_next(
            run["workflow_run_id"], revision_id, "org:1", "worker",
        )["status"] == "retry_wait"
        clock[0] += 600

    step = workflows.get_revision(
        run["workflow_run_id"], revision_id, "org:1"
    )["steps"][0]
    assert step["execution_status"] == "queued"
    assert step["terminal_reason"] == "connection is unavailable"
    # Eight outage ticks, and the whole retry budget is still intact.
    assert step["attempt"] - step["uncounted_attempts"] == 0


def test_an_unavailable_connection_pauses_rather_than_retrying(tmp_path):
    workflows = WorkflowRepository(str(tmp_path / "w.db"))
    actions = ActionRepository(str(tmp_path / "a.db"))
    run, revision = _write_revision(workflows)
    revision_id = revision["workflow_revision_id"]
    claim = workflows.claim_ready_step(
        run["workflow_run_id"], revision_id, "org:1", "worker", 4, 60,
    )
    step = workflows.get_revision(
        run["workflow_run_id"], revision_id, "org:1"
    )["steps"][0]

    with pytest.raises(PausedStepError, match="connection is unavailable"):
        WorkflowBrokerDispatcher(
            actions, _UnreachableBroker(), _Connections("disconnected"),
            workflows, clock=lambda: 5,
        )(step, claim)


def test_safe_write_failures_remain_retryable_instead_of_requiring_reconciliation():
    with pytest.raises(RetryableStepError):
        _raise_for_broker_failure(
            503,
            {"error": "provider operation failed safely", "outcome_certainty": "safe"},
            "write",
        )

    with pytest.raises(AmbiguousStepError):
        _raise_for_broker_failure(202, {"status": "execution_unknown"}, "write")


@pytest.mark.parametrize("status, category", [
    (403, "scope"),
    (403, "membership"),
    (422, "validation"),
    (409, "provider"),
])
def test_deterministic_slack_failures_are_correctable(status, category):
    with pytest.raises(CorrectableStepError, match=category):
        _raise_for_broker_failure(
            status,
            {"error": "slack_error", "category": category,
             "outcome_certainty": "safe"},
            "write",
        )


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


def test_rate_limited_read_is_retryable_with_provider_delay(tmp_path):
    workflows = WorkflowRepository(str(tmp_path / "w.db"))
    actions = ActionRepository(str(tmp_path / "a.db"))
    run = workflows.create_run("org:1", "user:1", "goal", 1)
    revision = workflows.create_revision(run["workflow_run_id"], "org:1", "graph", [{
        "step_id": "read", "capability_id": "slack.conversation.read",
        "capability_version": "1", "connection_id": "conn:1",
        "descriptor_snapshot_hash": "d", "input_hash": "i", "input": {},
        "depends_on": [], "effect": "read",
    }], 2)
    workflows.authorize_requested_read(
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
            return {"connection_id": connection_id, "status": "connected",
                    "credential_id": "cred:1", "credential_version": 1,
                    "granted_scopes": ["channels:history"]}
    class Broker:
        def execute(self, lease, binding, payload):
            return 429, {"error": "rate_limited", "retry_after": 17}
    from agents.orchestrator.workflow_executor import RetryableStepError
    with pytest.raises(RetryableStepError) as caught:
        WorkflowBrokerDispatcher(
            actions, Broker(), Connections(), workflows, clock=lambda: 5
        )(step, claim)
    assert caught.value.retry_after == 17


@pytest.mark.parametrize("connection", [
    {"status": "connected", "credential_version": 3},
    {"status": "disconnected", "credential_version": 2},
])
def test_write_rechecks_credential_version_and_connection_before_dispatch(
    tmp_path, connection
):
    workflows = WorkflowRepository(str(tmp_path / "w.db"))
    actions = ActionRepository(str(tmp_path / "a.db"))
    run = workflows.create_run("org:1", "user:1", "goal", 1)
    revision = workflows.create_revision(run["workflow_run_id"], "org:1", "graph", [{
        "step_id": "send", "capability_id": "slack.message.send",
        "capability_version": "1", "connection_id": "conn:1",
        "credential_version": 2, "descriptor_snapshot_hash": "d",
        "input_hash": "i", "input": {"channel_id": "C1", "text": "Hola"},
        "depends_on": [], "effect": "write",
    }], 2)
    workflows.record_approval(run["workflow_run_id"], revision["workflow_revision_id"],
                              "org:1", "graph", "user:1", 3)
    claim = workflows.claim_ready_step(run["workflow_run_id"], revision["workflow_revision_id"],
                                       "org:1", "worker", 4, 60)
    step = workflows.get_revision(run["workflow_run_id"], revision["workflow_revision_id"],
                                  "org:1")["steps"][0]
    class Connections:
        def get_installation(self, connection_id, tenant_id):
            return {**connection, "connection_id": connection_id,
                    "credential_id": "cred:1", "enabled_capabilities": ["slack.message.send"]}
    class Broker:
        def execute(self, *args):
            raise AssertionError("provider must not be called")
    dispatcher = WorkflowBrokerDispatcher(actions, Broker(), Connections(), workflows,
                                          clock=lambda: 5)
    with pytest.raises((PermissionError, RetryableStepError, PausedStepError)):
        dispatcher(step, claim)


def test_claimed_old_revision_cannot_dispatch_after_replan(tmp_path):
    workflows = WorkflowRepository(str(tmp_path / "w.db"))
    actions = ActionRepository(str(tmp_path / "a.db"))
    run = workflows.create_run("org:1", "user:1", "goal", 1)
    first = workflows.create_revision(
        run["workflow_run_id"], "org:1", "graph:1", [{
            "step_id": "send",
            "capability_id": "slack.message.send",
            "capability_version": "1.0.0",
            "connection_id": "conn:1",
            "credential_version": 1,
            "descriptor_snapshot_hash": "descriptor:1",
            "input_hash": "input:1",
            "input": {"channel_id": "C1", "text": "old"},
            "depends_on": [],
            "effect": "write",
        }], 2,
    )
    workflows.record_approval(
        run["workflow_run_id"], first["workflow_revision_id"],
        "org:1", "graph:1", "user:1", 3,
    )
    claim = workflows.claim_ready_step(
        run["workflow_run_id"], first["workflow_revision_id"],
        "org:1", "worker", 4, 60,
    )
    old_step = workflows.get_revision(
        run["workflow_run_id"], first["workflow_revision_id"], "org:1"
    )["steps"][0]

    workflows.create_revision(
        run["workflow_run_id"], "org:1", "graph:2", [{
            "step_id": "send",
            "capability_id": "slack.message.send",
            "capability_version": "1.0.0",
            "connection_id": "conn:1",
            "credential_version": 1,
            "descriptor_snapshot_hash": "descriptor:2",
            "input_hash": "input:2",
            "input": {"channel_id": "C1", "text": "new"},
            "depends_on": [],
            "effect": "write",
        }], 5,
    )

    class Connections:
        def get_installation(self, connection_id, tenant_id):
            return {
                "connection_id": connection_id,
                "status": "connected",
                "credential_id": "cred:1",
                "credential_version": 1,
                "granted_scopes": ["chat:write"],
            }

    class Broker:
        def execute(self, *_args):
            raise AssertionError("superseded revision reached provider dispatch")

    dispatcher = WorkflowBrokerDispatcher(
        actions, Broker(), Connections(), workflows, clock=lambda: 6,
    )

    with pytest.raises(PermissionError, match="approval expired"):
        dispatcher(old_step, claim)
    assert actions.get("proposal:%s:send" % first["workflow_revision_id"]) is None


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


@pytest.mark.parametrize("capability", [
    "slack.reaction.add", "slack.reaction.remove",
    "slack.message.pin", "slack.message.unpin",
])
def test_an_idempotent_write_retries_instead_of_demanding_reconciliation(
    capability,
):
    from libs.integrations.catalog import capability_retry_policy

    policy = capability_retry_policy(capability, "write")
    assert policy == "idempotent"

    # Repeating these converges on the same state, so an unknown outcome is
    # a retry, not a case for a human to reconcile.
    with pytest.raises(RetryableStepError):
        _raise_for_broker_failure(202, {"status": "execution_unknown"},
                                  "write", policy)
    with pytest.raises(RetryableStepError):
        _raise_for_broker_failure(503, {"error": "unavailable"}, "write", policy)


@pytest.mark.parametrize("capability", [
    "slack.message.send", "slack.thread.reply",
    "slack.direct_message.send", "slack.bookmark.add",
])
def test_an_appending_write_still_requires_reconciliation(capability):
    from libs.integrations.catalog import capability_retry_policy

    policy = capability_retry_policy(capability, "write")
    assert policy == "reconcile"

    # Repeating these creates a second message or bookmark, so the outcome
    # must be established before anything retries.
    with pytest.raises(AmbiguousStepError):
        _raise_for_broker_failure(202, {"status": "execution_unknown"},
                                  "write", policy)
    with pytest.raises(AmbiguousStepError):
        _raise_for_broker_failure(503, {"error": "unavailable"}, "write", policy)


def test_a_read_is_never_ambiguous():
    from libs.integrations.catalog import capability_retry_policy

    assert capability_retry_policy("slack.conversation.read", "read") == "safe"
    with pytest.raises(RetryableStepError):
        _raise_for_broker_failure(202, {}, "read", "safe")


def test_a_deterministic_refusal_is_correctable_whatever_the_retry_policy():
    with pytest.raises(CorrectableStepError, match="membership"):
        _raise_for_broker_failure(
            403, {"error": "not_in_channel", "category": "membership"},
            "write", "idempotent",
        )
