import sqlite3

import pytest

from agents.orchestrator.action_repository import ActionRepository

NOW = 1_700_000_000


def _lease(repository, attempt):
    return repository.issue_lease(
        "user:alice", "agent:slack", "task:%d" % attempt, "credential:slack",
        ["slack.channels.list"], NOW + 60,
        workflow_revision_id="revision:1", step_id="resolve-slack-channel",
        plan_graph_hash="graph:1", connection_id="conn:slack", attempt=attempt,
    )


def test_retrying_a_step_supersedes_its_stranded_lease(tmp_path):
    repository = ActionRepository(str(tmp_path / "actions.sqlite"))

    first = _lease(repository, 0)
    second = _lease(repository, 1)

    assert first != second
    rows = repository._connection.execute(
        "SELECT attempt, revoked_at FROM capability_leases "
        "WHERE workflow_revision_id = 'revision:1' ORDER BY attempt"
    ).fetchall()
    assert [(r[0], r[1] is not None) for r in rows] == [(0, True), (1, False)]


def test_concurrent_steps_keep_independent_leases(tmp_path):
    repository = ActionRepository(str(tmp_path / "actions.sqlite"))
    repository.issue_lease(
        "user:alice", "agent:slack", "task:a", "credential:slack",
        ["slack.channels.list"], NOW + 60,
        workflow_revision_id="revision:1", step_id="step-a",
        plan_graph_hash="graph:1", connection_id="conn:slack", attempt=0,
    )
    repository.issue_lease(
        "user:alice", "agent:slack", "task:b", "credential:slack",
        ["slack.users.list"], NOW + 60,
        workflow_revision_id="revision:1", step_id="step-b",
        plan_graph_hash="graph:1", connection_id="conn:slack", attempt=0,
    )
    active = repository._connection.execute(
        "SELECT COUNT(*) FROM capability_leases WHERE revoked_at IS NULL "
        "AND consumed_at IS NULL"
    ).fetchone()[0]
    assert active == 2



def _read_step_fixture(tmp_path):
    """A claimed read step, wired exactly like the conversational resolver."""
    from agents.orchestrator.workflow_repository import WorkflowRepository

    workflows = WorkflowRepository(str(tmp_path / "w.db"))
    actions = ActionRepository(str(tmp_path / "a.db"))
    run = workflows.create_run("org:1", "user:1", "goal", 1)
    revision = workflows.create_revision(
        run["workflow_run_id"], "org:1", "graph", [{
            "step_id": "resolve-slack-channel",
            "capability_id": "slack.channels.list",
            "capability_version": "1.0.0", "connection_id": "conn:1",
            "descriptor_snapshot_hash": "d", "input_hash": "i",
            "input": {"limit": 200}, "depends_on": [], "effect": "read",
        }], 2)
    workflows.authorize_requested_read(
        run["workflow_run_id"], revision["workflow_revision_id"], "org:1",
        "graph", "user:1", 3,
    )
    return workflows, actions, run, revision


def test_a_stranded_lease_lets_the_read_step_retry_instead_of_going_unknown(tmp_path):
    from agents.orchestrator.workflow_broker_dispatcher import (
        WorkflowBrokerDispatcher,
    )

    workflows, actions, run, revision = _read_step_fixture(tmp_path)
    revision_id = revision["workflow_revision_id"]

    # Strand a lease exactly as an interrupted first attempt would.
    actions.issue_lease(
        "user:1", "agent:orchestrator", "task:stale", "cred:1",
        ["slack.channels.list"], 100,
        workflow_revision_id=revision_id, step_id="resolve-slack-channel",
        plan_graph_hash="graph", connection_id="conn:1", attempt=0, now_ts=4,
    )

    class Connections:
        def get_installation(self, connection_id, tenant_id):
            return {"connection_id": connection_id, "status": "connected",
                    "credential_id": "cred:1", "credential_version": 1,
                    "granted_scopes": ["channels:read"], "team_id": "T1",
                    "bot_user_id": "B1"}

    class Broker:
        def execute(self, lease, binding, payload):
            return 200, {"receipt": {"channels": [{"id": "C1", "name": "general"}]}}

    claim = workflows.claim_ready_step(
        run["workflow_run_id"], revision_id, "org:1", "worker", 4, 60,
    )
    step = workflows.get_revision(
        run["workflow_run_id"], revision_id, "org:1"
    )["steps"][0]

    result = WorkflowBrokerDispatcher(
        actions, Broker(), Connections(), workflows, clock=lambda: 5
    )(step, claim)

    assert result["receipt"]["channels"] == [{"id": "C1", "name": "general"}]
    active = actions._connection.execute(
        "SELECT COUNT(*) FROM capability_leases WHERE revoked_at IS NULL "
        "AND consumed_at IS NULL AND workflow_revision_id = ?", (revision_id,),
    ).fetchone()[0]
    assert active == 1


def test_an_unexpected_pre_dispatch_failure_never_reaches_the_provider(tmp_path):
    from agents.orchestrator.workflow_broker_dispatcher import (
        WorkflowBrokerDispatcher,
    )
    from agents.orchestrator.workflow_executor import CorrectableStepError

    workflows, actions, run, revision = _read_step_fixture(tmp_path)
    revision_id = revision["workflow_revision_id"]

    class BrokenActions:
        def __getattr__(self, name):
            return getattr(actions, name)

        def issue_lease(self, *args, **kwargs):
            raise sqlite3.IntegrityError("UNIQUE constraint failed")

    class Connections:
        def get_installation(self, connection_id, tenant_id):
            return {"connection_id": connection_id, "status": "connected",
                    "credential_id": "cred:1", "credential_version": 1,
                    "granted_scopes": ["channels:read"], "team_id": "T1",
                    "bot_user_id": "B1"}

    class Broker:
        def execute(self, *args):
            raise AssertionError("the provider must not be contacted")

    claim = workflows.claim_ready_step(
        run["workflow_run_id"], revision_id, "org:1", "worker", 4, 60,
    )
    step = workflows.get_revision(
        run["workflow_run_id"], revision_id, "org:1"
    )["steps"][0]

    with pytest.raises(CorrectableStepError, match="pre_dispatch:IntegrityError"):
        WorkflowBrokerDispatcher(
            BrokenActions(), Broker(), Connections(), workflows, clock=lambda: 5
        )(step, claim)


def _authority_binding(**overrides):
    binding = {
        "user_principal_id": "user:1", "agent_principal_id": "agent:1",
        "task_id": "task:1", "credential_id": "cred:1",
        "capability_id": "slack.search.messages",
        "workflow_revision_id": "revision:1", "step_id": "search",
        "plan_graph_hash": "graph:1", "connection_id": "conn:1", "attempt": 1,
        "authority_profile": "user",
        "authority_profile_id": "authority:1",
        "slack_subject_id": "U1",
    }
    binding.update(overrides)
    return binding


def _authority_lease(repository):
    return repository.issue_lease(
        "user:1", "agent:1", "task:1", "cred:1", ["slack.search.messages"],
        NOW + 60, workflow_revision_id="revision:1", step_id="search",
        plan_graph_hash="graph:1", connection_id="conn:1", attempt=1,
        now_ts=NOW, authority_profile="user",
        authority_profile_id="authority:1", slack_subject_id="U1",
    )


def test_a_lease_validates_only_for_the_identity_it_was_issued_to(tmp_path):
    repository = ActionRepository(str(tmp_path / "actions.sqlite"))
    lease = _authority_lease(repository)

    assert repository.validate_lease(lease, _authority_binding(), NOW) is True


@pytest.mark.parametrize("swap", [
    {"slack_subject_id": "U-someone-else"},
    {"authority_profile_id": "authority:other"},
    {"authority_profile": "bot"},
])
def test_swapping_the_acting_identity_invalidates_the_lease(tmp_path, swap):
    repository = ActionRepository(str(tmp_path / "actions.sqlite"))
    lease = _authority_lease(repository)

    # An approval names who will act. Substituting another identity afterwards
    # would make that approval a statement about nobody in particular.
    assert repository.validate_lease(
        lease, _authority_binding(**swap), NOW,
    ) is False


def test_a_bot_lease_still_validates_without_personal_fields(tmp_path):
    repository = ActionRepository(str(tmp_path / "actions.sqlite"))
    lease = repository.issue_lease(
        "user:1", "agent:1", "task:1", "cred:1", ["slack.message.send"],
        NOW + 60, workflow_revision_id="revision:1", step_id="send",
        plan_graph_hash="graph:1", connection_id="conn:1", attempt=1,
        now_ts=NOW,
    )

    binding = _authority_binding(
        capability_id="slack.message.send", step_id="send",
        authority_profile="bot", authority_profile_id=None,
        slack_subject_id=None,
    )

    assert repository.validate_lease(lease, binding, NOW) is True


def test_a_channel_effect_is_proposed_as_reinforced(tmp_path):
    from libs.integrations.catalog import capability_reinforced

    repository = ActionRepository(str(tmp_path / "actions.sqlite"))
    archive = repository.create_proposal(
        "user:1", "agent:1", "cred:1", "slack.channel.archive",
        {"channel_id": "C1"}, NOW + 60, workflow_revision_id="revision:1",
        step_id="archive", plan_graph_hash="graph:1", connection_id="conn:1",
        attempt=1, reinforced=capability_reinforced("slack.channel.archive"),
    )
    ordinary = repository.create_proposal(
        "user:1", "agent:1", "cred:1", "slack.message.send",
        {"channel_id": "C1", "text": "hola"}, NOW + 60,
        workflow_revision_id="revision:2", step_id="send",
        plan_graph_hash="graph:2", connection_id="conn:1", attempt=1,
        reinforced=capability_reinforced("slack.message.send"),
    )

    assert archive["reinforced"] == 1
    # Everyday messaging must not be dragged into step-up.
    assert ordinary["reinforced"] == 0
