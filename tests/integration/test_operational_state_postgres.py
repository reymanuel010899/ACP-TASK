import os
import base64
import uuid

import pytest
import psycopg

from libs.db import Database, bind_organization_id
from libs.integrations.catalog import account_state
from services.oauth.repository import PkceCipher, PostgresOAuthRepository
from services.session.repository import PostgresSessionRepository
from agents.orchestrator.dispatch_ledger import (
    AmbiguousDispatch,
    DuplicateDispatch,
    PostgresDispatchLedger,
)
from agents.orchestrator.action_repository import PostgresActionRepository
from agents.orchestrator.conversation_state import (
    PostgresConversationStateStore,
)
from agents.orchestrator.workflow_repository import PostgresWorkflowRepository
from agents.orchestrator.workflow_executor import WorkflowExecutor
from libs.spend_ledger import PostgresSpendLedger, SpendCeilingExceeded


NOW = 1_700_000_000


@pytest.fixture
def postgres_session_repository():
    pg_dsn = os.environ["DATABASE_URL"]
    principal_id = "user:pg-session:%s" % uuid.uuid4().hex
    with psycopg.connect(pg_dsn) as conn:
        conn.execute(
            "insert into identity.principals(principal_id, principal_type) "
            "values (%s, 'user')",
            (principal_id,),
        )
    db = Database(pg_dsn, min_size=1, max_size=4)
    repository = PostgresSessionRepository(
        db, idle_ttl_seconds=10, absolute_ttl_seconds=25
    )
    try:
        yield principal_id, repository, db
    finally:
        db.close()


def test_postgres_session_is_shared_replay_safe_and_revocable(
    postgres_session_repository,
):
    principal_id, first, db = postgres_session_repository
    second = PostgresSessionRepository(
        db, idle_ttl_seconds=10, absolute_ttl_seconds=25
    )

    proof = "proof:first:%s" % principal_id
    created = first.create(principal_id, proof, NOW)
    assert second.resolve(created["session_id"], NOW + 1) == {
        "principal_id": principal_id,
        "created_at": NOW,
        "expires_at": NOW + 25,
        "idle_ttl_seconds": 10,
    }
    assert second.csrf_matches(created["session_id"], created["csrf_token"])
    assert second.count_active(NOW + 1) == 1

    with pytest.raises(ValueError, match="already been consumed"):
        second.create(principal_id, proof, NOW + 2)

    assert second.revoke(created["session_id"], NOW + 3)
    assert first.resolve(created["session_id"], NOW + 3) is None


def test_postgres_session_expiry_and_authentication_attestation_match_contract(
    postgres_session_repository,
):
    principal_id, repository, _db = postgres_session_repository
    created = repository.create(
        principal_id, "proof:expiry:%s" % principal_id, NOW
    )

    assert repository.authentication_attestation(
        created["session_id"], NOW + 5, freshness_seconds=5
    )["fresh"]
    assert repository.resolve(created["session_id"], NOW + 11) is None
    assert repository.authentication_attestation(
        created["session_id"], NOW + 11
    )["reason"] == "session_absent"


def test_postgres_session_rotation_revokes_previous_session_atomically(
    postgres_session_repository,
):
    principal_id, repository, _db = postgres_session_repository
    first = repository.create(
        principal_id, "proof:rotation:1:%s" % principal_id, NOW
    )
    second = repository.create(
        principal_id,
        "proof:rotation:2:%s" % principal_id,
        NOW + 1,
        previous_session_id=first["session_id"],
    )

    assert repository.resolve(first["session_id"], NOW + 1) is None
    assert repository.resolve(second["session_id"], NOW + 1) is not None


@pytest.fixture
def postgres_oauth_repository():
    pg_dsn = os.environ["DATABASE_URL"]
    suffix = uuid.uuid4().hex
    tenant_id = "org:pg-oauth:%s" % suffix
    principal_id = "user:pg-oauth:%s" % suffix
    credential_id = "credential:pg-oauth:%s" % suffix
    with psycopg.connect(pg_dsn) as conn:
        conn.execute(
            "insert into identity.organizations(organization_id, name) "
            "values (%s, 'OAuth test')",
            (tenant_id,),
        )
        conn.execute(
            "insert into identity.principals(principal_id, principal_type, "
            "home_organization_id) values (%s, 'user', %s)",
            (principal_id, tenant_id),
        )
        conn.execute(
            "insert into identity.organization_members("
            "organization_id, principal_id, role) values (%s, %s, 'owner')",
            (tenant_id, principal_id),
        )
        conn.execute(
            "insert into vault.credentials(credential_id, user_principal_id, "
            "name, credential_type, encrypted_data, nonce) "
            "values (%s, %s, 'OAuth test', 'oauth', 'sealed', 'nonce')",
            (credential_id, principal_id),
        )
    bind_organization_id(tenant_id)
    db = Database(pg_dsn, min_size=1, max_size=4)
    sessions = PostgresSessionRepository(db)
    session = sessions.create(principal_id, "proof:%s" % suffix, NOW)
    key = bytes(range(32))
    repository = PostgresOAuthRepository(
        db, PkceCipher(base64.urlsafe_b64encode(key).decode("ascii"))
    )
    try:
        yield tenant_id, principal_id, credential_id, session, repository, db
    finally:
        bind_organization_id(None)
        db.close()


def test_postgres_oauth_state_is_encrypted_and_consumed_exactly_once(
    postgres_oauth_repository,
):
    tenant_id, principal_id, _credential_id, session, repository, db = (
        postgres_oauth_repository
    )
    created = repository.create_transaction(
        "oauth:%s" % uuid.uuid4().hex,
        session["session_id"],
        principal_id,
        "google",
        ["calendar.read"],
        ["calendar.events.list"],
        "state-secret",
        "pkce-secret",
        "/integrations",
        NOW,
        tenant_id=tenant_id,
        app_id="google-app",
    )
    assert created["pkce_verifier"] == "pkce-secret"
    with db.connection() as conn:
        stored = conn.execute(
            "select pkce_verifier_ciphertext "
            "from integrations.oauth_transactions "
            "where transaction_id = %s",
            (created["transaction_id"],),
        ).fetchone()[0]
    assert stored != "pkce-secret"
    assert "pkce-secret" not in stored

    consumed = repository.consume_transaction(
        "state-secret", session["session_id"], principal_id, NOW + 1
    )
    assert consumed["pkce_verifier"] == "pkce-secret"
    assert repository.consume_transaction(
        "state-secret", session["session_id"], principal_id, NOW + 1
    ) is None
    assert repository.find_by_state("state-secret")["pkce_verifier"] == ""


def test_postgres_oauth_installations_and_voice_routes_are_shared(
    postgres_oauth_repository,
):
    tenant_id, principal_id, credential_id, _session, repository, db = (
        postgres_oauth_repository
    )
    installation = repository.upsert_installation(
        tenant_id,
        principal_id,
        "slack",
        "slack-app",
        credential_id,
        ["chat:write"],
        ["slack.message.send"],
        NOW,
        team_id="team:%s" % uuid.uuid4().hex,
        team_name="Test team",
    )
    second = PostgresOAuthRepository(repository.db, repository.pkce_cipher)
    assert second.get_installation(
        installation["connection_id"], tenant_id
    )["principal_id"] == principal_id
    assert second.list_tenant_installations(tenant_id, "slack") == [installation]

    routes = [{
        "route_id": "support",
        "department": "support",
        "language": "es",
        "destination": "+18095550101",
        "timezone": "America/Santo_Domingo",
        "start_hour": 8,
        "end_hour": 18,
        "ring_seconds": 20,
        "total_budget_seconds": 60,
        "priority": 1,
    }]
    repository.replace_voice_routes(tenant_id, routes)
    assert second.voice_routes(tenant_id) == routes


def test_postgres_personal_authority_requires_owner_or_live_delegation(
    postgres_oauth_repository,
):
    tenant_id, principal_id, credential_id, _session, repository, _db = (
        postgres_oauth_repository
    )
    connection = repository.upsert_installation(
        tenant_id, principal_id, "slack", "authority-app", credential_id,
        ["search:read"], ["slack.search"], NOW,
        team_id="authority-team:%s" % uuid.uuid4().hex,
    )
    profile = repository.record_authority_profile(
        tenant_id, connection["connection_id"], "user", principal_id,
        credential_id, ["search:read"], NOW, slack_subject_id="U123",
        enabled=True,
    )
    assert repository.authorize_personal_authority(
        tenant_id, connection["connection_id"], "user", principal_id,
        "slack_search", NOW,
    )["reason"] == "requester_is_subject"

    other = "user:delegate:%s" % uuid.uuid4().hex
    assert repository.authorize_personal_authority(
        tenant_id, connection["connection_id"], "user", other,
        "slack_search", NOW, consent_owner_principal_id=principal_id,
    )["reason"] == "delegation_absent"
    repository.grant_authority_delegation(
        tenant_id, profile["authority_profile_id"], other, "slack_search",
        "incident triage", principal_id, NOW + 60, NOW,
    )
    assert repository.authorize_personal_authority(
        tenant_id, connection["connection_id"], "user", other,
        "slack_search", NOW, consent_owner_principal_id=principal_id,
    )["reason"] == "delegated"
    assert repository.authorize_personal_authority(
        tenant_id, connection["connection_id"], "user", other,
        "slack_search", NOW + 61, consent_owner_principal_id=principal_id,
    )["reason"] == "delegation_absent"

    assert repository.revoke_authority_profile(
        tenant_id, connection["connection_id"], "user", principal_id,
        NOW + 70,
    )
    assert repository.authorize_personal_authority(
        tenant_id, connection["connection_id"], "user", principal_id,
        "slack_search", NOW + 71,
    )["reason"] == "authority_profile_revoked"


def test_postgres_provider_authority_and_emergency_stop_are_durable(
    postgres_oauth_repository,
):
    tenant_id, principal_id, credential_id, _session, repository, _db = (
        postgres_oauth_repository
    )
    connection = repository.upsert_installation(
        tenant_id, principal_id, "twilio", "AC123", credential_id,
        [], ["twilio.sms.send"], NOW,
    )
    state = account_state({
        "provider": "twilio",
        "account_id": "AC123",
        "status": "verified",
        "families": ["sms:send"],
        "senders": [{
            "sender_id": "+15165550101",
            "family": "sms",
            "countries": ["US"],
        }],
    })
    scopes = repository.record_verified_account(
        tenant_id, connection["connection_id"], "twilio", "AC123", state
    )
    assert "twilio:sms:send" in scopes
    assert repository.control_plane_state(tenant_id)["emergency_stop"] is False
    stopped = repository.set_emergency_stop(
        tenant_id, True, NOW, reason="incident",
        acting_principal_id=principal_id,
    )
    assert stopped["emergency_stop"] is True
    assert stopped["stop_reason"] == "incident"
    resumed = repository.set_emergency_stop(
        tenant_id, False, NOW + 1, acting_principal_id=principal_id,
    )
    assert resumed["emergency_stop"] is False


def test_postgres_dispatch_intent_precedes_provider_and_is_not_duplicated(
    postgres_oauth_repository,
):
    tenant_id, _principal_id, _credential_id, _session, _repository, db = (
        postgres_oauth_repository
    )
    ledger = PostgresDispatchLedger(db, clock=lambda: NOW)
    observed = []

    result = ledger.dispatch(
        tenant_id, "dispatch:1", "effect:1", {"body": "hello"},
        "callback:signed", lambda intent: (
            observed.append(intent) or {"provider_id": "SM123", "status": "queued"}
        ),
    )
    assert result["provider_id"] == "SM123"
    assert observed[0]["callback_token"] == "callback:signed"
    assert observed[0]["attempt_count"] == 1
    assert ledger.get(tenant_id, "dispatch:1")["status"] == "accepted"
    with pytest.raises(DuplicateDispatch):
        ledger.dispatch(
            tenant_id, "dispatch:1", "effect:1", {"body": "hello"},
            "callback:signed", lambda _intent: {"provider_id": "SM456"},
        )


def test_postgres_dispatch_ambiguous_outcome_requires_reconciliation(
    postgres_oauth_repository,
):
    tenant_id, _principal_id, _credential_id, _session, _repository, db = (
        postgres_oauth_repository
    )
    ledger = PostgresDispatchLedger(db, clock=lambda: NOW)

    with pytest.raises(AmbiguousDispatch):
        ledger.dispatch(
            tenant_id, "dispatch:ambiguous", "effect:ambiguous", {},
            "callback:ambiguous",
            lambda _intent: (_ for _ in ()).throw(TimeoutError()),
        )
    assert ledger.get(tenant_id, "dispatch:ambiguous")["status"] == "ambiguous"
    assert ledger.reconcile(
        tenant_id, "dispatch:ambiguous", "SM789", "delivered"
    )


def _action_authority(postgres_oauth_repository):
    tenant_id, principal_id, credential_id, _session, _repository, db = (
        postgres_oauth_repository
    )
    suffix = uuid.uuid4().hex
    agent_id = "agent:pg-action:%s" % suffix
    capability_id = "capability.pg-action.%s" % suffix
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute(
            "insert into identity.principals(principal_id, principal_type, "
            "home_organization_id) values (%s, 'agent', %s)",
            (agent_id, tenant_id),
        )
        conn.execute(
            "insert into catalog.capabilities("
            "capability_id, version, description) values (%s, '1', 'test')",
            (capability_id,),
        )
    return tenant_id, principal_id, agent_id, credential_id, capability_id, db


def test_postgres_action_approval_is_bound_and_consumed_once(
    postgres_oauth_repository,
):
    tenant_id, user_id, agent_id, credential_id, capability_id, db = (
        _action_authority(postgres_oauth_repository)
    )
    first = PostgresActionRepository(db)
    second = PostgresActionRepository(db)
    proposal = first.create_proposal(
        user_id, agent_id, credential_id, capability_id,
        {"to": "+18095550101", "body": "hello"}, NOW + 60,
        proposal_id="proposal:%s" % uuid.uuid4().hex,
        idempotency_key="effect:%s" % uuid.uuid4().hex,
        tenant_id=tenant_id,
    )
    assert second.get(
        proposal["proposal_id"], tenant_id=tenant_id
    )["payload"] == proposal["payload"]
    assert first.decide(
        proposal["proposal_id"], proposal["version"], user_id, True, NOW,
        tenant_id,
    )
    binding = {
        key: proposal[key] for key in (
            "proposal_id", "version", "user_principal_id",
            "agent_principal_id", "credential_id", "capability_id",
            "payload_hash", "idempotency_key", "workflow_revision_id",
            "step_id", "plan_graph_hash", "connection_id", "attempt",
        )
    }
    binding["tenant_id"] = tenant_id
    assert second.consume_approval(binding, NOW + 1)["status"] == "executing"
    assert first.consume_approval(binding, NOW + 1) is None
    assert first.mark_dispatched(
        proposal["proposal_id"], proposal["version"], NOW + 2
    )
    assert second.complete_execution(
        proposal["proposal_id"], proposal["version"],
        {"provider_id": "SM123"}, NOW + 3,
        broker_response={"accepted": True},
    )
    completed = first.get(
        proposal["proposal_id"], proposal["version"], tenant_id
    )
    assert completed["status"] == "completed"
    assert completed["receipt"] == {"provider_id": "SM123"}


def test_postgres_capability_lease_is_single_use_and_binding_strict(
    postgres_oauth_repository,
):
    tenant_id, user_id, agent_id, credential_id, capability_id, db = (
        _action_authority(postgres_oauth_repository)
    )
    repository = PostgresActionRepository(db)
    binding = {
        "tenant_id": tenant_id,
        "user_principal_id": user_id,
        "agent_principal_id": agent_id,
        "task_id": "task:1",
        "credential_id": credential_id,
        "capability_id": capability_id,
        "workflow_revision_id": "revision:1",
        "step_id": "step:1",
        "plan_graph_hash": "graph:1",
        "connection_id": "connection:1",
        "attempt": 1,
        "authority_profile": "bot",
    }
    lease = repository.issue_lease(
        user_id, agent_id, binding["task_id"], credential_id,
        [capability_id], NOW + 60,
        workflow_revision_id=binding["workflow_revision_id"],
        step_id=binding["step_id"],
        plan_graph_hash=binding["plan_graph_hash"],
        connection_id=binding["connection_id"], attempt=1, now_ts=NOW,
        tenant_id=tenant_id,
    )
    assert repository.validate_lease(lease, binding, NOW)
    changed = dict(binding, connection_id="connection:other")
    assert not repository.validate_lease(lease, changed, NOW)
    assert repository.consume_lease(lease, binding, NOW + 1)
    assert not repository.consume_lease(lease, binding, NOW + 1)


def test_postgres_task_conversation_is_shared_and_expires_durably(
    postgres_oauth_repository,
):
    tenant_id, _user_id, _credential_id, _session, _repository, db = (
        postgres_oauth_repository
    )
    current = [NOW]
    first = PostgresConversationStateStore(
        db, clock=lambda: current[0], timeout_seconds=10
    )
    second = PostgresConversationStateStore(
        db, clock=lambda: current[0], timeout_seconds=10
    )
    task_id = "task:conversation:%s" % uuid.uuid4().hex
    created = first.create_task(
        task_id, "agent:delivery", "delivery.quote",
        known_inputs={"origin": "Santo Domingo"},
    )
    assert second.get_task(task_id)["known_inputs"] == {
        "origin": "Santo Domingo"
    }
    second.create_task(
        task_id, "agent:delivery", "delivery.quote",
        known_inputs={"destination": "Santiago"},
    )
    assert first.get_task(task_id)["known_inputs"] == {
        "origin": "Santo Domingo", "destination": "Santiago"
    }
    current[0] = NOW + 11
    assert second.get_task(task_id) is None
    assert first.get_task(task_id, include_expired=True)["status"] == "expired"


def test_postgres_workflow_claim_is_exclusive_and_completion_is_durable(
    postgres_oauth_repository,
):
    tenant_id, user_id, _agent_id, _credential_id, capability_id, db = (
        _action_authority(postgres_oauth_repository)
    )
    first = PostgresWorkflowRepository(db)
    second = PostgresWorkflowRepository(db)
    run = first.create_run(tenant_id, user_id, "goal:hash", NOW)
    revision = first.create_revision(
        run["workflow_run_id"], tenant_id, "graph:hash", [{
            "step_id": "read",
            "capability_id": capability_id,
            "capability_version": "1",
            "descriptor_snapshot_hash": "descriptor:hash",
            "input_hash": "input:hash",
            "input": {"query": "status"},
            "depends_on": [],
            "effect": "read",
        }], NOW + 1,
    )
    revision_id = revision["workflow_revision_id"]
    assert second.authorize_requested_read(
        run["workflow_run_id"], revision_id, tenant_id, "graph:hash",
        user_id, NOW + 2,
    )
    claim = first.claim_ready_step(
        run["workflow_run_id"], revision_id, tenant_id, "worker:one",
        NOW + 3, 30,
    )
    assert claim["step_id"] == "read"
    assert second.claim_ready_step(
        run["workflow_run_id"], revision_id, tenant_id, "worker:two",
        NOW + 3, 30,
    ) is None
    assert second.persist_completion(
        revision_id, "read", tenant_id, claim["attempt"],
        {"provider_id": "read:1"}, None, NOW + 4,
        output={"answer": "ok"},
    )
    completed = first.get_revision(
        run["workflow_run_id"], revision_id, tenant_id
    )
    assert completed["status"] == "completed"
    assert completed["steps"][0]["output"] == {"answer": "ok"}
    assert second.get_step_receipt(
        revision_id, "read", tenant_id
    ) == {"provider_id": "read:1"}


@pytest.mark.parametrize(
    "effect, expected_status", [("read", "queued"), ("write", "execution_unknown")]
)
def test_postgres_workflow_expired_claim_recovery_is_effect_safe(
    postgres_oauth_repository, effect, expected_status,
):
    tenant_id, user_id, _agent_id, _credential_id, capability_id, db = (
        _action_authority(postgres_oauth_repository)
    )
    repository = PostgresWorkflowRepository(db)
    run = repository.create_run(tenant_id, user_id, "goal:recover", NOW)
    revision = repository.create_revision(
        run["workflow_run_id"], tenant_id, "graph:recover", [{
            "step_id": effect,
            "capability_id": capability_id,
            "capability_version": "1",
            "descriptor_snapshot_hash": "descriptor:recover",
            "input_hash": "input:recover",
            "input": {},
            "depends_on": [],
            "effect": effect,
        }], NOW + 1,
    )
    if effect == "read":
        repository.authorize_requested_read(
            run["workflow_run_id"], revision["workflow_revision_id"],
            tenant_id, "graph:recover", user_id, NOW + 2,
        )
    else:
        repository.record_approval(
            run["workflow_run_id"], revision["workflow_revision_id"],
            tenant_id, "graph:recover", user_id, NOW + 2,
        )
    repository.claim_ready_step(
        run["workflow_run_id"], revision["workflow_revision_id"], tenant_id,
        "worker:crashed", NOW + 3, 5,
    )
    repository.recover_expired_claims(NOW + 9)
    recovered = repository.get_revision(
        run["workflow_run_id"], revision["workflow_revision_id"], tenant_id
    )
    assert recovered["steps"][0]["execution_status"] == expected_status


def test_postgres_workflow_executor_runs_dependency_chain_once(
    postgres_oauth_repository,
):
    tenant_id, user_id, _agent_id, _credential_id, capability_id, db = (
        _action_authority(postgres_oauth_repository)
    )
    repository = PostgresWorkflowRepository(db)
    run = repository.create_run(tenant_id, user_id, "goal:chain", NOW)
    revision = repository.create_revision(
        run["workflow_run_id"], tenant_id, "graph:chain", [
            {
                "step_id": "one", "capability_id": capability_id,
                "capability_version": "1",
                "descriptor_snapshot_hash": "descriptor:one",
                "input_hash": "input:one", "input": {},
                "depends_on": [], "effect": "read",
            },
            {
                "step_id": "two", "capability_id": capability_id,
                "capability_version": "1",
                "descriptor_snapshot_hash": "descriptor:two",
                "input_hash": "input:two", "input": {},
                "depends_on": ["one"], "effect": "read",
            },
        ], NOW + 1,
    )
    repository.authorize_requested_read(
        run["workflow_run_id"], revision["workflow_revision_id"], tenant_id,
        "graph:chain", user_id, NOW + 2,
    )
    calls = []

    def execute(step, _claim):
        calls.append(step["step_id"])
        return {
            "receipt": {"provider_id": "read:%s" % step["step_id"]},
            "output": {"step": step["step_id"]},
        }

    result = WorkflowExecutor(
        repository, execute, clock=lambda: NOW + 3
    ).run_until_blocked(
        run["workflow_run_id"], revision["workflow_revision_id"], tenant_id,
        "worker:chain",
    )
    assert result["status"] == "complete"
    assert calls == ["one", "two"]


def test_postgres_outbox_is_ordered_idempotent_and_restart_safe(
    postgres_oauth_repository,
):
    tenant_id, _user_id, _credential_id, _session, _oauth, db = (
        postgres_oauth_repository
    )
    first = PostgresWorkflowRepository(db)
    second = PostgresWorkflowRepository(db)
    aggregate_id = "conversation:%s" % uuid.uuid4().hex
    event_one = first.append_outbox_event(
        tenant_id, "conversation", aggregate_id, "workflow.outcome",
        {"status": "complete"}, "outbox:dedupe:one:%s" % aggregate_id,
        NOW,
    )
    duplicate = second.append_outbox_event(
        tenant_id, "conversation", aggregate_id, "workflow.outcome",
        {"status": "complete"}, "outbox:dedupe:one:%s" % aggregate_id,
        NOW + 1,
    )
    event_two = second.append_outbox_event(
        tenant_id, "conversation", aggregate_id, "workflow.outcome",
        {"status": "retry_wait"}, "outbox:dedupe:two:%s" % aggregate_id,
        NOW + 2,
    )
    assert duplicate["event_id"] == event_one["event_id"]
    assert event_one["aggregate_version"] == 1
    assert event_two["aggregate_version"] == 2
    assert first.count_outbox_events(
        tenant_id, "outbox:dedupe:one:%s" % aggregate_id
    ) == 1

    claim_one = first.claim_outbox_event(
        "projector:crashed", NOW + 3, visibility_timeout=5,
        tenant_id=tenant_id,
    )
    assert claim_one["event_id"] == event_one["event_id"]
    assert second.claim_outbox_event(
        "projector:other", NOW + 4, tenant_id=tenant_id
    ) is None
    recovered = second.claim_outbox_event(
        "projector:restart", NOW + 9, tenant_id=tenant_id
    )
    assert recovered["event_id"] == event_one["event_id"]
    assert recovered["attempts"] == 2
    assert second.complete_outbox_event(
        recovered["event_id"], tenant_id, "projector:restart", NOW + 10
    )
    claim_two = first.claim_outbox_event(
        "projector:next", NOW + 11, tenant_id=tenant_id
    )
    assert claim_two["event_id"] == event_two["event_id"]


def test_postgres_outbox_retry_dead_letter_and_monotonic_watermark(
    postgres_oauth_repository,
):
    tenant_id, _user_id, _credential_id, _session, _oauth, db = (
        postgres_oauth_repository
    )
    repository = PostgresWorkflowRepository(db)
    aggregate_id = "conversation:%s" % uuid.uuid4().hex
    event = repository.append_outbox_event(
        tenant_id, "conversation", aggregate_id, "workflow.outcome",
        {"status": "complete"}, "outbox:dead:%s" % aggregate_id, NOW,
        max_attempts=2,
    )
    first = repository.claim_outbox_event(
        "projector:one", NOW + 1, tenant_id=tenant_id
    )
    assert repository.fail_outbox_event(
        first["event_id"], tenant_id, "projector:one", NOW + 2,
        "temporary", 3,
    ) == "retry"
    assert repository.claim_outbox_event(
        "projector:early", NOW + 4, tenant_id=tenant_id
    ) is None
    second = repository.claim_outbox_event(
        "projector:two", NOW + 5, tenant_id=tenant_id
    )
    assert repository.fail_outbox_event(
        second["event_id"], tenant_id, "projector:two", NOW + 6,
        "permanent", 0,
    ) == "dead_letter"

    assert repository.advance_projection_watermark(
        tenant_id, "conversation", aggregate_id, 1, event["event_id"],
        NOW + 7,
    )
    assert not repository.advance_projection_watermark(
        tenant_id, "conversation", aggregate_id, 1, event["event_id"],
        NOW + 8,
    )
    watermark = repository.get_projection_watermark(
        tenant_id, "conversation", aggregate_id
    )
    assert watermark["projected_version"] == 1
    assert watermark["last_event_id"] == event["event_id"]


def test_postgres_concierge_turn_is_idempotent_and_survives_restart(
    postgres_oauth_repository,
):
    tenant_id, principal_id, _credential_id, _session, _oauth, db = (
        postgres_oauth_repository
    )
    first = PostgresWorkflowRepository(db)
    second = PostgresWorkflowRepository(db)
    conversation = first.create_conversation(
        tenant_id, principal_id, NOW, locale="es"
    )
    assert conversation["state_version"] == 1
    assert conversation["locale"] == "es"
    started = first.begin_conversation_turn(
        conversation["conversation_id"], tenant_id, principal_id, "turn:1",
        1, {"message": "Busca el canal general"}, NOW + 1,
    )
    duplicate_start = second.begin_conversation_turn(
        conversation["conversation_id"], tenant_id, principal_id, "turn:1",
        1, {"message": "Busca el canal general"}, NOW + 2,
    )
    assert started["turn"]["status"] == "started"
    assert duplicate_start["duplicate"]

    committed = second.commit_conversation_turn(
        conversation["conversation_id"], tenant_id, principal_id, "turn:1",
        1, {"status": "needs_input", "blocking_need": {
            "field": "active_channel"
        }}, {"message": "¿Cuál canal?"}, NOW + 3,
    )
    assert committed["conversation"]["state_version"] == 2
    assert committed["conversation"]["status"] == "needs_input"
    assert committed["response"] == {"message": "¿Cuál canal?"}
    replay = first.commit_conversation_turn(
        conversation["conversation_id"], tenant_id, principal_id, "turn:1",
        1, {}, {"ignored": True}, NOW + 4,
    )
    assert replay["duplicate"]
    assert replay["response"] == {"message": "¿Cuál canal?"}

    with pytest.raises(RuntimeError, match="version conflict"):
        first.begin_conversation_turn(
            conversation["conversation_id"], tenant_id, principal_id,
            "turn:stale", 1, {"message": "stale"}, NOW + 5,
        )


def test_postgres_concierge_owner_binding_and_expiry_are_enforced(
    postgres_oauth_repository,
):
    tenant_id, principal_id, _credential_id, _session, _oauth, db = (
        postgres_oauth_repository
    )
    repository = PostgresWorkflowRepository(db)
    conversation = repository.create_conversation(
        tenant_id, principal_id, NOW, ttl_seconds=5
    )
    assert repository.get_conversation(
        conversation["conversation_id"], tenant_id, "user:other", NOW + 1
    ) is None
    assert repository.get_conversation(
        conversation["conversation_id"], tenant_id, principal_id, NOW + 6
    ) is None
    expired = repository.get_conversation(
        conversation["conversation_id"], tenant_id, principal_id, NOW + 6,
        include_terminal=True,
    )
    assert expired["status"] == "expired"


def test_postgres_spend_reservation_is_shared_and_idempotently_settled(
    postgres_oauth_repository,
):
    tenant_id, _principal_id, _credential_id, _session, _oauth, db = (
        postgres_oauth_repository
    )
    first = PostgresSpendLedger(db, clock=lambda: NOW)
    second = PostgresSpendLedger(db, clock=lambda: NOW + 1)
    campaign_id = "campaign:%s" % uuid.uuid4().hex
    first.set_ceiling(tenant_id, "account", tenant_id, "10.00")
    first.set_ceiling(tenant_id, "campaign", campaign_id, "3.00")
    reservation_id = "effect:%s" % uuid.uuid4().hex
    reserved = first.reserve(
        tenant_id, reservation_id, "sms", "2.50", campaign_id
    )
    assert str(reserved["reserved"]) == "2.5"
    replay = second.reserve(
        tenant_id, reservation_id, "sms", "2.50", campaign_id
    )
    assert replay["reservation_id"] == reservation_id
    with pytest.raises(ValueError, match="another estimate"):
        second.reserve(
            tenant_id, reservation_id, "sms", "2.00", campaign_id
        )
    settled = second.settle(tenant_id, reservation_id, "2.10")
    assert str(settled["settled"]) == "2.1"
    assert first.settle(
        tenant_id, reservation_id, "2.10"
    )["status"] == "settled"
    account = first.budget(tenant_id, "account", tenant_id)
    assert account["reserved_micros"] == 0
    assert account["settled_micros"] == 2_100_000


def test_postgres_spend_ceiling_release_and_brand_volume_are_atomic(
    postgres_oauth_repository,
):
    tenant_id, _principal_id, _credential_id, _session, _oauth, db = (
        postgres_oauth_repository
    )
    ledger = PostgresSpendLedger(db, clock=lambda: NOW)
    ledger.set_ceiling(tenant_id, "account", tenant_id, "1.00")
    reservation_id = "effect:%s" % uuid.uuid4().hex
    ledger.reserve(tenant_id, reservation_id, "sms", "0.75")
    with pytest.raises(SpendCeilingExceeded, match="account_ceiling_exhausted"):
        ledger.reserve(
            tenant_id, "effect:%s" % uuid.uuid4().hex, "sms", "0.50"
        )
    assert ledger.release(tenant_id, reservation_id)
    assert not ledger.release(tenant_id, reservation_id)
    assert ledger.meter_brand_volume(
        tenant_id, "brand:test", "2026-08-26", 2
    ) == 1
    assert ledger.meter_brand_volume(
        tenant_id, "brand:test", "2026-08-26", 2
    ) == 2
    with pytest.raises(SpendCeilingExceeded, match="brand_daily_volume_exhausted"):
        ledger.meter_brand_volume(
            tenant_id, "brand:test", "2026-08-26", 2
        )
