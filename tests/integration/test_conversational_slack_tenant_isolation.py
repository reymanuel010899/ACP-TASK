import pytest

from agents.orchestrator.conversation_state import ConciergeConversationStore
from agents.orchestrator.dynamic_workflow_service import DynamicWorkflowService
from agents.orchestrator.workflow_repository import WorkflowRepository
from libs.integrations.catalog import slack_definitions


class _TenantConnections:
    def list_tenant_installations(self, tenant_id, provider):
        assert provider == "slack"
        if tenant_id != "org:acme":
            return []
        return [{
            "connection_id": "conn:acme", "team_name": "Acme",
            "status": "connected", "credential_version": 1,
            "granted_scopes": ["channels:read", "chat:write"],
            "enabled_capabilities": ["slack.channels.list", "slack.message.send"],
        }]


def test_tenant_member_can_resolve_own_installation_but_other_tenant_cannot_discover_it(tmp_path):
    workflows = WorkflowRepository(str(tmp_path / "workflows.db"))
    store = ConciergeConversationStore(workflows, clock=lambda: 10)
    service = DynamicWorkflowService(
        object(), slack_definitions(), _TenantConnections(), workflows,
        conversation_store=store, clock=lambda: 10,
    )

    own = service.coordinate_slack_turn(
        "org:acme", "user:member", "Read #general",
        channels=[{"id": "C1", "name": "general"}],
    )
    foreign = service.coordinate_slack_turn(
        "org:other", "user:member", "Read #general",
        channels=[{"id": "C1", "name": "general"}],
    )

    assert own["resolved"]["active_connection"] == {"id": "conn:acme", "label": "Acme"}
    assert foreign["state"] == "needs_input"
    assert foreign["need"]["field"] == "workspace"
    assert foreign["need"]["options"] == []

    with pytest.raises(KeyError, match="conversation unavailable"):
        service.materialize_slack_write(
            own["conversation_id"], "org:other", "user:member",
            "slack.message.send", "No autorizado",
        )


def _resolving_conversation(tmp_path, name="isolation.db", now=10):
    workflows = WorkflowRepository(str(tmp_path / name))
    store = ConciergeConversationStore(workflows, clock=lambda: now)
    service = DynamicWorkflowService(
        object(), slack_definitions(), _TenantConnections(), workflows,
        conversation_store=store, clock=lambda: now,
    )
    intake = service.coordinate_slack_turn(
        "org:acme", "user:member", "Manda en #general que Hola equipo"
    )
    resolving = service.advance_slack_turn(
        intake["conversation_id"], "org:acme", "user:member",
        "Manda en #general que Hola equipo", intake,
    )
    return workflows, store, service, intake["conversation_id"], resolving


def test_switching_tenant_between_resolution_and_continuation_denies_every_reference(tmp_path):
    workflows, store, service, conversation_id, resolving = _resolving_conversation(
        tmp_path
    )
    request = store.get(conversation_id, "org:acme", "user:member")[
        "resolution_request"
    ]
    resolver_run_id = request["resolver_run_id"]
    revision_id = resolving["workflow"]["revisionId"]

    assert store.get(conversation_id, "org:other", "user:member") is None
    assert store.get(conversation_id, "org:acme", "user:intruder") is None
    assert workflows.get_slack_resolver_run(resolver_run_id, "org:other") is None
    assert workflows.get_slack_resolver_run(
        resolver_run_id, "org:acme", principal_id="user:intruder"
    ) is None
    assert workflows.get_revision_by_id(revision_id, "org:other") is None
    assert workflows.list_resumable_slack_resolver_runs(11) and not [
        run for run in workflows.list_resumable_slack_resolver_runs(11)
        if run["tenant_id"] != "org:acme"
    ]
    assert service.apply_slack_resolver_completion(
        "org:other", conversation_id,
        {"resolver_run_id": resolver_run_id, "principal_id": "user:member"}, 11,
    ) is False
    assert service.apply_slack_resolver_completion(
        "org:acme", conversation_id,
        {"resolver_run_id": resolver_run_id, "principal_id": "user:intruder"}, 11,
    ) is False

    with pytest.raises(KeyError, match="conversation unavailable"):
        workflows.start_slack_resolver_run(
            conversation_id, "org:other", "user:member", "conn:acme",
            "channel", "query:general", 1, 11,
        )
    with pytest.raises(KeyError, match="conversation unavailable"):
        workflows.store_slack_conversation_entity(
            conversation_id, "org:other", "user:member", "channel",
            "conn:acme", "T1", "C1", {"id": "C1", "name": "general"},
            {"source": "conversations.list"}, 11, 71,
        )


def test_expiring_a_conversation_with_an_unapproved_effect_strands_its_entities(tmp_path):
    workflows = WorkflowRepository(str(tmp_path / "expiry.db"))
    store = ConciergeConversationStore(workflows, clock=lambda: 10)
    service = DynamicWorkflowService(
        object(), slack_definitions(), _TenantConnections(), workflows,
        conversation_store=store, clock=lambda: 10,
    )
    intake = service.coordinate_slack_turn(
        "org:acme", "user:member", "Manda en #general que Hola equipo",
        channels=[{"id": "C1", "name": "general"}],
    )
    conversation_id = intake["conversation_id"]
    draft = service.advance_slack_turn(
        conversation_id, "org:acme", "user:member",
        "Manda en #general que Hola equipo", intake,
    )
    assert draft["state"] == "awaiting_approval"
    stored = store.get(conversation_id, "org:acme", "user:member")
    entity = workflows.store_slack_conversation_entity(
        conversation_id, "org:acme", "user:member", "channel", "conn:acme",
        "T1", "C1", {"id": "C1", "name": "general"},
        {"source": "conversations.list"}, 10, 600,
        expected_state_version=stored["state_version"],
    )

    expired_at = 10 + 10_000
    assert store.get(conversation_id, "org:acme", "user:member") is not None
    assert workflows.get_conversation(
        conversation_id, "org:acme", "user:member", expired_at
    ) is None
    assert workflows.get_slack_conversation_entity(
        entity["entity_ref_id"], conversation_id, "org:acme", "user:member",
        expired_at, include_stale=True,
    ) is None
    assert workflows.list_resumable_slack_resolver_runs(expired_at) == []
    with pytest.raises(KeyError, match="conversation unavailable"):
        workflows.store_slack_conversation_entity(
            conversation_id, "org:acme", "user:member", "channel", "conn:acme",
            "T1", "C2", {"id": "C2", "name": "anuncios"},
            {"source": "conversations.list"}, expired_at, expired_at + 60,
        )
    with pytest.raises(KeyError, match="conversation unavailable"):
        workflows.start_slack_resolver_run(
            conversation_id, "org:acme", "user:member", "conn:acme",
            "channel", "query:anuncios", 1, expired_at,
        )


def test_two_tabs_race_one_turn_and_the_loser_rebases_on_current_state(tmp_path):
    workflows = WorkflowRepository(str(tmp_path / "tabs.db"))
    conversation = workflows.create_conversation(
        "org:acme", "user:member", 10, ttl_seconds=600
    )
    conversation_id = conversation["conversation_id"]
    base_version = int(conversation["state_version"])

    workflows.begin_conversation_turn(
        conversation_id, "org:acme", "user:member", "tab-a", base_version,
        {"text": "Hola equipo"}, 11,
    )
    with pytest.raises(RuntimeError, match="conversation turn already in progress"):
        workflows.begin_conversation_turn(
            conversation_id, "org:acme", "user:member", "tab-b", base_version,
            {"text": "Mejor en #anuncios"}, 11,
        )

    winner = workflows.commit_conversation_turn(
        conversation_id, "org:acme", "user:member", "tab-a", base_version,
        {"status": "resolving"}, {"state": "resolving"}, 12,
    )
    with pytest.raises(RuntimeError, match="conversation version conflict"):
        workflows.begin_conversation_turn(
            conversation_id, "org:acme", "user:member", "tab-b", base_version,
            {"text": "Mejor en #anuncios"}, 13,
        )

    current = workflows.get_conversation(
        conversation_id, "org:acme", "user:member", 13
    )
    assert winner["conversation"]["state_version"] == base_version + 1
    assert current["state_version"] == base_version + 1
    assert current["status"] == "resolving"

    workflows.begin_conversation_turn(
        conversation_id, "org:acme", "user:member", "tab-b",
        current["state_version"], {"text": "Mejor en #anuncios"}, 14,
    )
    rebased = workflows.commit_conversation_turn(
        conversation_id, "org:acme", "user:member", "tab-b",
        current["state_version"], {"status": "ready"}, {"state": "ready"}, 14,
    )
    assert rebased["conversation"]["state_version"] == base_version + 2
    assert rebased["conversation"]["status"] == "ready"


def test_replaying_a_timed_out_turn_repeats_its_transition_without_new_work(tmp_path):
    workflows = WorkflowRepository(str(tmp_path / "replay.db"))
    conversation = workflows.create_conversation(
        "org:acme", "user:member", 10, ttl_seconds=600
    )
    conversation_id = conversation["conversation_id"]
    base_version = int(conversation["state_version"])

    workflows.begin_conversation_turn(
        conversation_id, "org:acme", "user:member", "turn:1", base_version,
        {"text": "Manda en #general"}, 11,
    )
    first = workflows.commit_conversation_turn(
        conversation_id, "org:acme", "user:member", "turn:1", base_version,
        {"status": "retrieving"}, {"state": "retrieving"}, 12,
    )
    replay = workflows.begin_conversation_turn(
        conversation_id, "org:acme", "user:member", "turn:1", base_version,
        {"text": "Manda en #general"}, 13,
    )

    assert first["duplicate"] is False
    assert replay["duplicate"] is True
    assert replay["response"] == {"state": "retrieving"}
    assert replay["conversation"]["state_version"] == base_version + 1
    assert workflows.get_conversation(
        conversation_id, "org:acme", "user:member", 13
    )["state_version"] == base_version + 1
    assert workflows.count_outbox_events(
        "org:acme", "conversation-turn:%s:turn:1" % conversation_id
    ) == 1


class _DirectMessageConnections:
    def list_tenant_installations(self, tenant_id, provider):
        if tenant_id != "org:acme":
            return []
        return [{
            "connection_id": "conn:acme", "team_name": "Acme",
            "status": "connected", "credential_version": 1,
            "granted_scopes": ["users:read", "chat:write", "im:write"],
            "enabled_capabilities": [
                "slack.users.list", "slack.message.send", "slack.dm.send"],
        }]


def test_two_matching_people_ask_once_with_labels_that_leak_no_profile_data(tmp_path):
    workflows = WorkflowRepository(str(tmp_path / "ambiguous.db"))
    store = ConciergeConversationStore(workflows, clock=lambda: 10)
    service = DynamicWorkflowService(
        object(), slack_definitions(), _DirectMessageConnections(), workflows,
        conversation_store=store, clock=lambda: 10,
    )
    intake = service.coordinate_slack_turn(
        "org:acme", "user:member", "Mándale a María que hola"
    )
    conversation_id = intake["conversation_id"]
    resolving = service.advance_slack_turn(
        conversation_id, "org:acme", "user:member",
        "Mándale a María que hola", intake,
    )
    assert resolving["state"] == "retrieving"
    request = store.get(conversation_id, "org:acme", "user:member")[
        "resolution_request"
    ]
    assert request["field"] == "person"

    revision = workflows.get_revision_by_id(
        resolving["workflow"]["revisionId"], "org:acme"
    )
    claim = workflows.claim_ready_step(
        revision["workflow_run_id"], revision["workflow_revision_id"],
        "org:acme", "worker:1", 10, 30,
    )
    workflows.persist_completion(
        revision["workflow_revision_id"], "resolve-slack-person", "org:acme",
        claim["attempt"], {"ok": True}, {}, 10,
        output={"users": [
            {"id": "U1", "display_name": "María", "real_name": "María Ruiz",
             "handle": "maria", "email": "maria@acme.com",
             "phone": "+34600000000", "title": "CTO"},
            {"id": "U2", "display_name": "María", "real_name": "María Soto",
             "handle": "msoto", "email": "msoto@acme.com",
             "phone": "+34600000001", "is_admin": True},
        ]},
    )
    assert workflows.sync_conversation_workflow_outcome(
        revision["workflow_revision_id"], "org:acme", {"status": "complete"}, 10
    )

    conversation = store.get(conversation_id, "org:acme", "user:member")
    need = conversation["blocking_need"]
    assert conversation["status"] == "needs_input"
    assert need["kind"] == "selection"
    assert need["field"] == "person"
    assert [option["id"] for option in need["options"]] == ["U1", "U2"]
    for leaked in ("email", "acme.com", "phone", "+3460", "title", "is_admin"):
        assert leaked not in str(need)

    run = workflows.get_slack_resolver_run(
        request["resolver_run_id"], "org:acme"
    )
    assert run["status"] == "completed"
    assert run["outcome"]["kind"] == "ambiguous"
    assert workflows.count_outbox_events(
        "org:acme", "slack-resolver:%s" % request["resolver_run_id"]
    ) == 1
