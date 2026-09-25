"""Emergency stop: account-wide, durable, and enforced at the broker.

The stop is deliberately not total. It blocks new dispatch and degrades
inbound handling; it never blocks reconciliation or provider-event ingestion.
A stop that froze those would strand every in-flight effect at exactly the
moment an operator needs a truthful dispatched-versus-prevented count, and
would mean no campaign could ever drain.
"""

from agents.orchestrator.action_repository import ActionRepository
from agents.orchestrator.reconciliation import WorkflowReconciler
from agents.orchestrator.workflow_broker_dispatcher import (
    WorkflowBrokerDispatcher,
)
from agents.orchestrator.workflow_executor import WorkflowExecutor
from agents.orchestrator.workflow_repository import WorkflowRepository
from libs.integrations.catalog import slack_definitions
from libs.integrations.control_plane import (
    EMERGENCY_STOP,
    build_tenant_control_plane,
)
from services.action_broker.app import ActionBroker
from services.action_broker.reconciliation import SlackReconciler
from services.oauth.repository import OAuthRepository
from services.workflow_worker.app import WorkflowWorker


TENANT = "org:acme"
OTHER_TENANT = "org:beta"
NOW = 10


class FakeSlack:
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


def _write_workflow(repository, tenant=TENANT, text="Hola"):
    run = repository.create_run(tenant, "user:alice", "goal", 1)
    revision = repository.create_revision(
        run["workflow_run_id"], tenant, "graph", [{
            "step_id": "send", "capability_id": "slack.message.send",
            "capability_version": "1.0.0", "connection_id": "conn:s",
            "descriptor_snapshot_hash": "d", "input_hash": "i",
            "input": {"channel_id": "C1", "text": text},
            "depends_on": [], "effect": "write",
        }], 2,
    )
    repository.record_approval(
        run["workflow_run_id"], revision["workflow_revision_id"], tenant,
        "graph", "user:alice", 3, ttl_seconds=10 ** 6,
    )
    return run, revision


def _executor(workflows, actions, broker, now, policy=None):
    return WorkflowExecutor(
        workflows,
        WorkflowBrokerDispatcher(
            actions, broker, Connections(), workflows, clock=lambda: now,
        ),
        policy=policy,
        clock=lambda: now,
    )


def _control_plane(tmp_path, name="control.db"):
    repository = OAuthRepository(str(tmp_path / name))
    plane = build_tenant_control_plane(repository, slack_definitions())
    # Read through on every call: a stop an operator just ordered must not be
    # served from a cache that predates it.
    plane.cache_seconds = 0
    return repository, plane


def test_a_stop_parks_queued_work_and_reports_what_it_prevented(tmp_path):
    workflows = WorkflowRepository(str(tmp_path / "w.db"))
    actions = ActionRepository(str(tmp_path / "a.db"))
    control, plane = _control_plane(tmp_path)
    control.set_capability_family_enabled(TENANT, "slack_messaging", True, NOW)
    slack = FakeSlack()
    done_run, done_revision = _write_workflow(workflows, text="Ya salio")
    _executor(
        workflows, actions, RecordingBroker(actions, slack, NOW), NOW,
        policy=plane.decide_step,
    ).run_next(
        done_run["workflow_run_id"], done_revision["workflow_revision_id"],
        TENANT, "worker-1",
    )
    held_run, held_revision = _write_workflow(workflows, text="No sale")

    control.set_emergency_stop(
        TENANT, True, NOW + 1, reason="paged", acting_principal_id="user:ana",
    )
    outcome = _executor(
        workflows, actions, RecordingBroker(actions, slack, NOW), NOW,
        policy=plane.decide_step,
    ).run_next(
        held_run["workflow_run_id"], held_revision["workflow_revision_id"],
        TENANT, "worker-1",
    )

    assert outcome["status"] == "paused_by_policy"
    assert outcome["reason"] == EMERGENCY_STOP
    # Parked, not failed: the work is intact and waiting for the stop to lift.
    held = workflows.get_revision(
        held_run["workflow_run_id"], held_revision["workflow_revision_id"],
        TENANT,
    )["steps"][0]
    assert held["execution_status"] == "paused_by_policy"
    assert slack.created == ["Ya salio"]
    counts = workflows.effect_disposition_counts(TENANT)
    assert counts["dispatched"] == 1
    assert counts["prevented"] == 1
    assert counts["uncertain"] == 0


def test_the_counts_separate_uncertain_from_dispatched_and_prevented(tmp_path):
    workflows = WorkflowRepository(str(tmp_path / "w.db"))
    actions = ActionRepository(str(tmp_path / "a.db"))
    control, plane = _control_plane(tmp_path)
    control.set_capability_family_enabled(TENANT, "slack_messaging", True, NOW)
    slack = FakeSlack()
    run, revision = _write_workflow(workflows)
    _executor(
        workflows, actions,
        RecordingBroker(actions, slack, NOW, lose_response=True), NOW,
        policy=plane.decide_step,
    ).run_next(
        run["workflow_run_id"], revision["workflow_revision_id"], TENANT,
        "worker-1",
    )
    control.set_emergency_stop(
        TENANT, True, NOW + 1, acting_principal_id="user:ana",
    )

    counts = workflows.effect_disposition_counts(TENANT)

    # Collapsing uncertain into dispatched would make the stop's own report
    # the least trustworthy thing on the operator's screen.
    assert counts["uncertain"] == 1
    assert counts["dispatched"] == 0
    assert counts["prevented"] == 0


def test_an_effect_left_unreconciled_at_stop_time_still_reaches_a_verdict(
    tmp_path,
):
    workflows = WorkflowRepository(str(tmp_path / "w.db"))
    actions = ActionRepository(str(tmp_path / "a.db"))
    control, plane = _control_plane(tmp_path)
    control.set_capability_family_enabled(TENANT, "slack_messaging", True, NOW)
    slack = FakeSlack()
    run, revision = _write_workflow(workflows)
    revision_id = revision["workflow_revision_id"]
    dispatched = _executor(
        workflows, actions,
        RecordingBroker(actions, slack, NOW, lose_response=True), NOW,
        policy=plane.decide_step,
    ).run_next(run["workflow_run_id"], revision_id, TENANT, "worker-1")
    assert dispatched["status"] == "execution_unknown"

    control.set_emergency_stop(
        TENANT, True, NOW + 1, acting_principal_id="user:ana",
    )
    verdicts = WorkflowReconciler(
        workflows, actions, {"slack": SlackReconciler(slack)},
    ).run_once(NOW + 10)

    # This is the whole carve-out. A stop that blocked the reconciling read
    # would freeze this effect as uncertain forever, and the operator's
    # dispatched-versus-prevented count would be a guess.
    assert [verdict["status"] for verdict in verdicts] == ["completed"]
    assert workflows.get_revision(
        run["workflow_run_id"], revision_id, TENANT
    )["steps"][0]["execution_status"] == "completed"
    assert slack.created == ["Hola"]
    assert plane.decide(
        TENANT, capability_id="slack.conversation.read", effect="read",
    )


def test_the_broker_refuses_a_stopped_accounts_write_even_with_a_valid_lease(
    tmp_path,
):
    actions = ActionRepository(str(tmp_path / "a.db"))
    control, plane = _control_plane(tmp_path)
    control.set_capability_family_enabled(TENANT, "slack_messaging", True, NOW)
    payload = {"channel_id": "C1", "text": "Hola"}
    proposal = actions.create_proposal(
        "user:alice", "agent:orchestrator", "cred:1", "slack.message.send",
        payload, NOW + 300,
    )
    actions.decide(proposal["proposal_id"], 1, "user:alice", True, NOW)
    lease = actions.issue_lease(
        "user:alice", "agent:orchestrator", "task-1", "cred:1",
        ["slack.message.send"], NOW + 60,
    )
    binding = {
        "proposal_id": proposal["proposal_id"], "version": proposal["version"],
        "user_principal_id": "user:alice",
        "agent_principal_id": "agent:orchestrator", "task_id": "task-1",
        "credential_id": "cred:1", "capability_id": "slack.message.send",
        "payload_hash": proposal["payload_hash"],
        "idempotency_key": proposal["idempotency_key"],
        "tenant_id": TENANT, "connection_id": "conn:s",
    }
    broker = ActionBroker(
        actions, object(), object(), object(), lambda: NOW,
        dispatch_policy=plane.decide_binding,
    )
    # Before the stop the gate is not what refuses; the broker gets past it
    # and fails later on its own unrelated preconditions.
    assert broker.execute(lease, binding, payload)[1]["error"] != EMERGENCY_STOP

    control.set_emergency_stop(
        TENANT, True, NOW + 1, acting_principal_id="user:ana",
    )
    status, body = broker.execute(lease, binding, payload)

    # Enforced here and not only in the orchestrator: the orchestrator is the
    # thing being stopped, so a stop honoured only there is bypassable by any
    # other caller holding a lease (KTD20).
    assert status == 403
    assert body["error"] == EMERGENCY_STOP


def test_a_stop_on_one_account_leaves_every_other_account_dispatching(tmp_path):
    workflows = WorkflowRepository(str(tmp_path / "w.db"))
    actions = ActionRepository(str(tmp_path / "a.db"))
    control, plane = _control_plane(tmp_path)
    for tenant in (TENANT, OTHER_TENANT):
        control.set_capability_family_enabled(
            tenant, "slack_messaging", True, NOW,
        )
    slack = FakeSlack()
    stopped_run, stopped_revision = _write_workflow(workflows, TENANT, "Nope")
    running_run, running_revision = _write_workflow(
        workflows, OTHER_TENANT, "Sale",
    )
    control.set_emergency_stop(
        TENANT, True, NOW + 1, acting_principal_id="user:ana",
    )
    executor = _executor(
        workflows, actions, RecordingBroker(actions, slack, NOW), NOW,
        policy=plane.decide_step,
    )

    stopped = executor.run_next(
        stopped_run["workflow_run_id"],
        stopped_revision["workflow_revision_id"], TENANT, "worker-1",
    )
    running = executor.run_next(
        running_run["workflow_run_id"],
        running_revision["workflow_revision_id"], OTHER_TENANT, "worker-1",
    )

    assert stopped["status"] == "paused_by_policy"
    assert running["status"] == "step_completed"
    assert slack.created == ["Sale"]


def test_one_administrator_cannot_stop_another_tenants_account(tmp_path):
    control, plane = _control_plane(tmp_path)
    control.set_capability_family_enabled(
        OTHER_TENANT, "slack_messaging", True, NOW,
    )

    control.set_emergency_stop(
        TENANT, True, NOW + 1, acting_principal_id="user:ana",
    )
    control.set_capability_family_enabled(TENANT, "slack_messaging", False, NOW)

    # Every write here is keyed by the tenant the caller's own session
    # resolved to; there is no argument that names another account.
    assert control.control_plane_state(OTHER_TENANT)["emergency_stop"] is False
    assert plane.decide(
        OTHER_TENANT, capability_id="slack.message.send", effect="write",
    )


def test_a_stop_activated_mid_dispatch_records_the_effect_exactly_once(
    tmp_path,
):
    workflows = WorkflowRepository(str(tmp_path / "w.db"))
    actions = ActionRepository(str(tmp_path / "a.db"))
    control, plane = _control_plane(tmp_path)
    control.set_capability_family_enabled(TENANT, "slack_messaging", True, NOW)
    slack = FakeSlack()
    run, revision = _write_workflow(workflows)
    revision_id = revision["workflow_revision_id"]

    class StopMidFlight(RecordingBroker):
        """Order the stop after the provider call, before the response lands."""

        def execute(self, lease, binding, payload):
            result = super().execute(lease, binding, payload)
            control.set_emergency_stop(
                TENANT, True, NOW + 1, acting_principal_id="user:ana",
            )
            return result

    outcome = _executor(
        workflows, actions, StopMidFlight(actions, slack, NOW), NOW,
        policy=plane.decide_step,
    ).run_next(run["workflow_run_id"], revision_id, TENANT, "worker-1")

    # Dispatched or prevented, never both: the effect that reached the
    # provider is recorded as dispatched, and the stop only governs what
    # comes next.
    assert outcome["status"] == "step_completed"
    assert slack.created == ["Hola"]
    counts = workflows.effect_disposition_counts(TENANT)
    assert (counts["dispatched"], counts["prevented"]) == (1, 0)
    second = _executor(
        workflows, actions, StopMidFlight(actions, slack, NOW), NOW,
        policy=plane.decide_step,
    ).run_next(run["workflow_run_id"], revision_id, TENANT, "worker-1")
    assert second["status"] in ("complete", "blocked")
    assert slack.created == ["Hola"]


def test_lifting_a_stop_releases_the_work_it_held_on_the_next_tick(tmp_path):
    workflows = WorkflowRepository(str(tmp_path / "w.db"))
    actions = ActionRepository(str(tmp_path / "a.db"))
    control, plane = _control_plane(tmp_path)
    control.set_capability_family_enabled(TENANT, "slack_messaging", True, NOW)
    slack = FakeSlack()
    run, revision = _write_workflow(workflows)
    revision_id = revision["workflow_revision_id"]
    control.set_emergency_stop(
        TENANT, True, NOW, acting_principal_id="user:ana",
    )
    executor = _executor(
        workflows, actions, RecordingBroker(actions, slack, NOW), NOW,
        policy=plane.decide_step,
    )
    executor.run_next(run["workflow_run_id"], revision_id, TENANT, "worker-1")
    assert workflows.get_revision(
        run["workflow_run_id"], revision_id, TENANT
    )["steps"][0]["execution_status"] == "paused_by_policy"

    control.set_emergency_stop(
        TENANT, False, NOW + 1, acting_principal_id="user:ana",
    )
    WorkflowWorker(workflows, executor, worker_id="worker-1").run_once()

    # Without this the switch is one-way in practice: prevented work would
    # never become dispatched, whatever the operator did afterwards.
    assert workflows.get_revision(
        run["workflow_run_id"], revision_id, TENANT
    )["steps"][0]["execution_status"] == "completed"
    assert slack.created == ["Hola"]


def test_a_stop_survives_a_process_restart_with_no_environment_change(tmp_path):
    path = str(tmp_path / "restart.db")
    first = OAuthRepository(path)
    first.set_emergency_stop(
        TENANT, True, NOW, reason="paged", acting_principal_id="user:ana",
    )
    first.close()

    second = OAuthRepository(path)
    plane = build_tenant_control_plane(second, slack_definitions())

    assert plane.emergency_stop(TENANT) is True
    assert second.control_plane_state(TENANT)["stop_reason"] == "paged"
