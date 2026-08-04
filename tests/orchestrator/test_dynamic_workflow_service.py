import pytest

from agents.orchestrator.dynamic_workflow_service import DynamicWorkflowService
from agents.orchestrator.conversation_state import ConciergeConversationStore
from agents.orchestrator.planner import descriptor_hash
from agents.orchestrator.workflow_repository import WorkflowRepository
from libs.integrations.catalog import TrustedCapabilityDefinition
from libs.integrations.catalog import slack_definitions
from agents.orchestrator.workflow_models import (
    SlackInterpretation,
    SlackInterpretationCorrection,
    SlackInterpretationSlot,
    SlackOperationCandidate,
    SlackOperationDependency,
)
from agents.orchestrator.slack_operations import SlackOperationManifestError


class _SlackConnections:
    def __init__(self, status="connected", scopes=None, enabled=None):
        self.status = status
        self.scopes = list(scopes if scopes is not None else ["chat:write"])
        self.enabled = list(enabled if enabled is not None else ["slack.message.send"])

    def list_tenant_installations(self, tenant, provider):
        return [{
            "connection_id": "conn:s", "team_id": "T1", "team_name": "Acme",
            "status": self.status, "credential_version": 1,
            "granted_scopes": self.scopes, "enabled_capabilities": self.enabled,
        }]


class _SlackProposalBrain:
    def __init__(self, proposals):
        self.proposals = list(proposals)
        self.contexts = []

    def understand_slack(self, text, context):
        self.contexts.append(context)
        return self.proposals.pop(0)


def _post_interpretation(channel="general", message="Hola equipo"):
    return SlackInterpretation(
        operations=[SlackOperationCandidate(
            operation_id="slack.message.send", confidence=0.95,
        )],
        slots=[
            SlackInterpretationSlot(name="channel", value=channel, provenance="current_turn"),
            SlackInterpretationSlot(name="message", value=message, provenance="current_turn"),
        ],
        locale="es", confidence=0.95,
    )


def test_live_registry_brain_post_reaches_exact_approval(tmp_path):
    brain = _SlackProposalBrain([_post_interpretation()])
    repository = WorkflowRepository(str(tmp_path / "brain-post.db"))
    store = ConciergeConversationStore(repository, clock=lambda: 10)
    service = DynamicWorkflowService(
        brain, slack_definitions(), _SlackConnections(), repository,
        conversation_store=store, clock=lambda: 10,
    )

    turn = service.coordinate_slack_turn(
        "org:1", "user:1", "publica el mensaje",
        channels=[{"id": "C1", "name": "general"}],
    )
    result = service.advance_slack_turn(
        turn["conversation_id"], "org:1", "user:1", "publica el mensaje", turn,
    )

    visible = {item["operation_id"] for item in brain.contexts[0]["slack_operation_projection"]}
    assert "slack.message.send" in visible
    assert "slack.reaction.add" not in visible
    assert result["state"] == "awaiting_approval"
    assert result["draft"]["destination_label"] == "#general"
    assert result["draft"]["text"] == "Hola equipo"


def test_model_channel_correction_preserves_exact_message(tmp_path):
    correction = SlackInterpretation(
        operations=[SlackOperationCandidate(
            operation_id="slack.message.send", confidence=0.95,
        )],
        corrections=[SlackInterpretationCorrection(
            slot="channel", replacement="anuncios", provenance="current_turn",
        )], locale="es", confidence=0.95,
    )
    brain = _SlackProposalBrain([_post_interpretation(), correction])
    repository = WorkflowRepository(str(tmp_path / "brain-correction.db"))
    store = ConciergeConversationStore(repository, clock=lambda: 10)
    service = DynamicWorkflowService(
        brain, slack_definitions(), _SlackConnections(), repository,
        conversation_store=store, clock=lambda: 10,
    )
    channels = [{"id": "C1", "name": "general"}, {"id": "C2", "name": "anuncios"}]
    first = service.coordinate_slack_turn("org:1", "user:1", "publica", channels=channels)
    service.advance_slack_turn(first["conversation_id"], "org:1", "user:1", "publica", first)

    changed = service.coordinate_slack_turn(
        "org:1", "user:1", "no, mejor anuncios",
        conversation_id=first["conversation_id"], channels=channels,
    )
    result = service.advance_slack_turn(
        first["conversation_id"], "org:1", "user:1", "no, mejor anuncios", changed,
    )
    assert result["draft"]["destination_label"] == "#anuncios"
    assert result["draft"]["text"] == "Hola equipo"


def test_grounded_entity_refs_and_correction_lineage_are_persisted(tmp_path):
    correction = SlackInterpretation(
        operations=[SlackOperationCandidate(
            operation_id="slack.message.send", confidence=0.96,
        )],
        corrections=[SlackInterpretationCorrection(
            slot="channel", replacement="anuncios", provenance="current_turn",
        )],
        locale="es", confidence=0.96,
    )
    brain = _SlackProposalBrain([_post_interpretation(), correction])
    repository = WorkflowRepository(str(tmp_path / "entity-lineage.db"))
    store = ConciergeConversationStore(repository, clock=lambda: 10)
    service = DynamicWorkflowService(
        brain, slack_definitions(), _SlackConnections(), repository,
        conversation_store=store, clock=lambda: 10,
    )
    channels = [
        {"id": "C1", "name": "general"},
        {"id": "C2", "name": "anuncios"},
    ]

    first = service.coordinate_slack_turn(
        "org:1", "user:1", "publica", channels=channels,
    )
    service.advance_slack_turn(
        first["conversation_id"], "org:1", "user:1", "publica", first,
    )
    initial = store.get(first["conversation_id"], "org:1", "user:1")
    initial_channel_ref = next(
        item for item in initial["entity_refs"]
        if item["slot"] == "active_channel"
    )
    assert initial["operation_candidates"] == [
        {"operation_id": "slack.message.send", "confidence": 0.95}
    ]
    assert {item["name"] for item in initial["slot_state"]} == {
        "channel", "message"
    }

    changed = service.coordinate_slack_turn(
        "org:1", "user:1", "no, mejor anuncios",
        conversation_id=first["conversation_id"], channels=channels,
    )
    persisted = store.get(first["conversation_id"], "org:1", "user:1")
    changed_channel_ref = next(
        item for item in persisted["entity_refs"]
        if item["slot"] == "active_channel"
    )

    assert changed["resolved"]["message_text"] == "Hola equipo"
    assert persisted["active_channel"] == {"id": "C2", "name": "anuncios"}
    assert changed_channel_ref["entity_ref_id"] != initial_channel_ref["entity_ref_id"]
    assert persisted["corrections"][-1]["slot"] == "channel"
    assert persisted["corrections"][-1]["previous_entity_ref_id"] == (
        initial_channel_ref["entity_ref_id"]
    )
    assert persisted["corrections"][-1]["replacement_entity_ref_id"] == (
        changed_channel_ref["entity_ref_id"]
    )
    assert persisted["known_inputs"]["message"] == "Hola equipo"


@pytest.mark.parametrize(
    "connections,writes,expected_code",
    [
        (_SlackConnections(status="revoked"), True, "connection_unavailable"),
        (_SlackConnections(scopes=[]), True, "missing_scope"),
        (_SlackConnections(), False, "feature_disabled"),
    ],
)
def test_known_but_unavailable_operation_returns_named_recovery(
    tmp_path, connections, writes, expected_code,
):
    brain = _SlackProposalBrain([_post_interpretation()])
    repository = WorkflowRepository(str(tmp_path / (expected_code + ".db")))
    service = DynamicWorkflowService(
        brain, slack_definitions(), connections, repository,
        conversation_store=ConciergeConversationStore(repository, clock=lambda: 10),
        slack_writes_enabled=writes, clock=lambda: 10,
    )

    result = service.coordinate_slack_turn("org:1", "user:1", "post message")

    assert result["state"] == "retryable_failure"
    assert result["error"]["code"] == expected_code
    assert result["recovery"]["action"]


def test_unregistered_model_operation_is_rejected_but_unknown_request_clarifies(tmp_path):
    unregistered = SlackInterpretation(
        operations=[SlackOperationCandidate(
            operation_id="slack.admin.fabricated", confidence=0.99,
        )], locale="en", confidence=0.99,
    )
    unknown = SlackInterpretation(locale="en", confidence=0.1)
    brain = _SlackProposalBrain([unregistered, unknown])
    repository = WorkflowRepository(str(tmp_path / "unregistered.db"))
    service = DynamicWorkflowService(
        brain, slack_definitions(), _SlackConnections(), repository,
        conversation_store=ConciergeConversationStore(repository, clock=lambda: 10),
        clock=lambda: 10,
    )

    rejected = service.coordinate_slack_turn("org:1", "user:1", "admin magic")
    clarified = service.coordinate_slack_turn("org:1", "user:1", "something mysterious")

    assert rejected["error"]["code"] == "unsupported_operation"
    assert rejected["recovery"]["action"] == "choose_supported_operation"
    assert clarified["state"] == "needs_input"
    assert clarified["need"]["field"] == "operation"


def test_model_named_unsupported_outcome_returns_limitation_not_generic_question(tmp_path):
    unsupported = SlackInterpretation(
        blockers=[{
            "kind": "unsupported_operation", "field": "operation",
            "question": "La búsqueda global no está disponible.",
        }],
        locale="es", confidence=0.95,
    )
    repository = WorkflowRepository(str(tmp_path / "named-unsupported.db"))
    service = DynamicWorkflowService(
        _SlackProposalBrain([unsupported]), slack_definitions(),
        _SlackConnections(), repository,
        conversation_store=ConciergeConversationStore(repository, clock=lambda: 10),
        clock=lambda: 10,
    )

    result = service.coordinate_slack_turn(
        "org:1", "user:1", "busca en todo Slack por presupuesto",
    )

    assert result["state"] == "retryable_failure"
    assert result["error"]["code"] == "unsupported_operation"
    assert result["recovery"]["action"] == "choose_supported_operation"


def test_live_status_remains_local_and_does_not_fabricate_workflow(tmp_path):
    interpretation = SlackInterpretation(
        operations=[SlackOperationCandidate(
            operation_id="slack.connection.status", confidence=0.99,
        )], locale="es", confidence=0.99,
    )
    brain = _SlackProposalBrain([interpretation])
    repository = WorkflowRepository(str(tmp_path / "status.db"))
    service = DynamicWorkflowService(
        brain, slack_definitions(), _SlackConnections(), repository,
        conversation_store=ConciergeConversationStore(repository, clock=lambda: 10),
        clock=lambda: 10,
    )

    result = service.coordinate_slack_turn("org:1", "user:1", "estado de slack")

    assert result["state"] == "completed"
    assert "Acme" in result["message"]
    assert repository.list_runnable_revisions() == []


def test_policy_hidden_operation_is_not_projected_and_has_named_recovery(tmp_path):
    brain = _SlackProposalBrain([_post_interpretation()])
    repository = WorkflowRepository(str(tmp_path / "policy-hidden.db"))
    service = DynamicWorkflowService(
        brain, slack_definitions(), _SlackConnections(), repository,
        conversation_store=ConciergeConversationStore(repository, clock=lambda: 10),
        slack_policy_visible=lambda operation: operation.operation_id != "slack.message.send",
        clock=lambda: 10,
    )

    result = service.coordinate_slack_turn("org:1", "user:1", "post message")

    visible = {item["operation_id"] for item in brain.contexts[0]["slack_operation_projection"]}
    assert "slack.message.send" not in visible
    assert result["error"]["code"] == "policy_denied"
    assert result["recovery"]["action"] == "contact_admin"


def test_compound_proposal_keeps_dependencies_without_partial_execution(tmp_path):
    proposal = SlackInterpretation(
        operations=[
            SlackOperationCandidate(operation_id="slack.conversation.read", confidence=0.9),
            SlackOperationCandidate(operation_id="slack.message.send", confidence=0.9),
        ],
        slots=[
            SlackInterpretationSlot(name="channel", value="general", provenance="current_turn"),
            SlackInterpretationSlot(name="message", value="Resumen listo", provenance="current_turn"),
        ],
        dependencies=[SlackOperationDependency(operation_index=1, depends_on_index=0)],
        locale="es", confidence=0.9,
    )
    brain = _SlackProposalBrain([proposal])
    connections = _SlackConnections(
        scopes=["channels:history", "chat:write"],
        enabled=["slack.conversation.read", "slack.message.send"],
    )
    repository = WorkflowRepository(str(tmp_path / "compound.db"))
    service = DynamicWorkflowService(
        brain, slack_definitions(), connections, repository,
        conversation_store=ConciergeConversationStore(repository, clock=lambda: 10),
        clock=lambda: 10,
    )

    turn = service.coordinate_slack_turn(
        "org:1", "user:1", "lee y publica",
        channels=[{"id": "C1", "name": "general"}],
    )
    result = service.advance_slack_turn(
        turn["conversation_id"], "org:1", "user:1", "lee y publica", turn,
    )

    assert [item["operation_id"] for item in turn["compound_operations"]] == [
        "slack.conversation.read", "slack.message.send",
    ]
    assert turn["dependencies"] == [{"operation_index": 1, "depends_on_index": 0}]
    assert result["error"]["code"] == "compound_execution_unavailable"
    assert repository.list_runnable_revisions() == []


def test_service_fails_closed_when_partial_slack_catalog_cannot_join_manifest(tmp_path):
    definitions = tuple(
        item for item in slack_definitions()
        if item.capability_id != "slack.message.send"
    )

    with pytest.raises(SlackOperationManifestError, match="not trusted"):
        DynamicWorkflowService(
            object(), definitions, _SlackConnections(),
            WorkflowRepository(str(tmp_path / "catalog-drift.db")),
        )


def test_typed_second_turn_extracts_only_exact_message_for_draft(tmp_path):
    first = SlackInterpretation(
        operations=[SlackOperationCandidate(
            operation_id="slack.message.send", confidence=0.95,
        )],
        slots=[SlackInterpretationSlot(
            name="channel", value="general", provenance="current_turn",
        )],
        locale="es", confidence=0.95,
    )
    second = SlackInterpretation(
        operations=[SlackOperationCandidate(
            operation_id="slack.message.send", confidence=0.95,
        )],
        slots=[SlackInterpretationSlot(
            name="message", value="Hola equipo", provenance="current_turn",
        )],
        locale="es", confidence=0.95,
    )
    brain = _SlackProposalBrain([first, second])
    repository = WorkflowRepository(str(tmp_path / "typed-message.db"))
    service = DynamicWorkflowService(
        brain, slack_definitions(), _SlackConnections(), repository,
        conversation_store=ConciergeConversationStore(repository, clock=lambda: 10),
        clock=lambda: 10,
    )
    initial = service.coordinate_slack_turn(
        "org:1", "user:1", "publica en general",
        channels=[{"id": "C1", "name": "general"}],
    )

    answered = service.coordinate_slack_turn(
        "org:1", "user:1", 'el mensaje es "Hola equipo"',
        conversation_id=initial["conversation_id"],
    )
    result = service.advance_slack_turn(
        initial["conversation_id"], "org:1", "user:1",
        'el mensaje es "Hola equipo"', answered,
    )

    assert answered["need"] is None
    assert result["state"] == "awaiting_approval"
    assert result["draft"]["text"] == "Hola equipo"


def test_service_uses_connected_catalog_and_persists_approval_ready_revision(tmp_path):
    definition = TrustedCapabilityDefinition(
        capability_id="synthetic.read", version="1", provider="synthetic",
        input_schema={"type": "object"}, output_schema={"type": "object"},
        required_scopes=frozenset({"read"}), effect="read", risk="low",
        retry_policy="safe", preview_fields=(), verifier=None,
    )
    class Connections:
        def list_installations(self, tenant, principal):
            return [{"connection_id": "conn:1", "status": "connected", "credential_version": 1,
                     "granted_scopes": ["read"], "enabled_capabilities": ["synthetic.read"]}]
    class Brain:
        def generate_plan(self, goal, capabilities, context):
            assert capabilities[0]["connections"] == ["conn:1"]
            return {"tenant_id": context["tenant_id"], "goal": goal, "steps": [{
                "step_id": "read", "capability_id": "synthetic.read", "capability_version": "1",
                "connection_id": "conn:1", "descriptor_snapshot_hash": descriptor_hash(definition),
                "input": {}, "depends_on": [],
            }]}
    service = DynamicWorkflowService(Brain(), [definition], Connections(), WorkflowRepository(str(tmp_path / "w.db")), rollout_version="r1")
    result = service.plan("org:1", "user:1", "read it")
    assert result["revision"]["steps"][0]["capability_id"] == "synthetic.read"
    assert result["plan"]["shadow_mode"] is True
    assert result["revision"]["status"] == "authorized"


def test_service_persists_one_slack_need_and_rejects_expired_pronoun(tmp_path):
    class Connections:
        def list_tenant_installations(self, tenant, provider):
            return [{"connection_id": "conn:s", "team_name": "Acme", "status": "connected"}]

    now = [100]
    repository = WorkflowRepository(str(tmp_path / "w.db"))
    store = ConciergeConversationStore(repository, clock=lambda: now[0], ttl_seconds=180)
    service = DynamicWorkflowService(
        object(), [], Connections(), repository, clock=lambda: now[0],
        conversation_store=store,
    )
    result = service.coordinate_slack_turn(
        "org:1", "user:1", "Manda un mensaje en #nuevo-canal",
        conversation_id="conversation:1",
        channels=[{"id": "C1", "name": "nuevo-canal"}],
    )
    assert result["need"]["field"] == "message_text"
    persisted = store.get("conversation:1", "org:1", "user:1")
    assert persisted["active_channel"]["id"] == "C1"
    assert persisted["blocking_need"]["field"] == "message_text"

    now[0] = 281
    expired = service.coordinate_slack_turn(
        "org:1", "user:1", "Respóndele ahí que sí",
        conversation_id="conversation:1",
    )
    assert expired["state"] == "expired"
    assert "active_channel" not in expired


def test_two_turn_http_service_path_materializes_the_preserved_exact_post(tmp_path):
    from libs.integrations.catalog import slack_definitions
    class Connections:
        def list_tenant_installations(self, tenant, provider):
            return [{"connection_id": "conn:s", "team_name": "Acme",
                     "status": "connected", "credential_version": 1,
                     "granted_scopes": ["chat:write"],
                     "enabled_capabilities": ["slack.message.send"]}]
    repository = WorkflowRepository(str(tmp_path / "w-two-turn.db"))
    store = ConciergeConversationStore(repository, clock=lambda: 10)
    service = DynamicWorkflowService(
        object(), slack_definitions(), Connections(), repository,
        conversation_store=store, clock=lambda: 10,
    )
    first = service.coordinate_slack_turn(
        "org:1", "user:1", "Manda un mensaje en #general",
        channels=[{"id": "C1", "name": "general"}],
    )
    second = service.coordinate_slack_turn(
        "org:1", "user:1", "Hola equipo",
        conversation_id=first["conversation_id"],
    )
    advanced = service.advance_slack_turn(
        first["conversation_id"], "org:1", "user:1", "Hola equipo", second
    )
    assert advanced["state"] == "awaiting_approval"
    assert advanced["draft"]["destination_label"] == "#general"
    assert advanced["draft"]["text"] == "Hola equipo"


def test_named_channel_starts_brokered_resolution_and_resumes_exact_post(tmp_path):
    from libs.integrations.catalog import slack_definitions
    class Connections:
        def list_tenant_installations(self, tenant, provider):
            return [{"connection_id": "conn:s", "team_name": "Acme",
                     "status": "connected", "credential_version": 1,
                     "granted_scopes": ["channels:read", "chat:write"],
                     "enabled_capabilities": ["slack.channels.list", "slack.message.send"]}]
    repository = WorkflowRepository(str(tmp_path / "resolver.db"))
    store = ConciergeConversationStore(repository, clock=lambda: 10)
    service = DynamicWorkflowService(
        object(), slack_definitions(), Connections(), repository,
        conversation_store=store, clock=lambda: 10,
    )
    intake = service.coordinate_slack_turn(
        "org:1", "user:1", "Manda en #general que Hola equipo"
    )
    resolving = service.advance_slack_turn(
        intake["conversation_id"], "org:1", "user:1",
        "Manda en #general que Hola equipo", intake,
    )
    assert resolving["state"] == "retrieving"
    revision = repository.get_revision_by_id(
        resolving["workflow"]["revisionId"], "org:1"
    )
    assert revision["steps"][0]["capability_id"] == "slack.channels.list"
    assert repository.revision_authorization_mode(
        revision["workflow_run_id"], revision["workflow_revision_id"],
        "org:1", revision["plan_graph_hash"], 10,
    ) == "requested_read"

    claim = repository.claim_ready_step(
        revision["workflow_run_id"], revision["workflow_revision_id"],
        "org:1", "worker:1", 10, 30,
    )
    repository.persist_completion(
        revision["workflow_revision_id"], "resolve-slack-channel", "org:1",
        claim["attempt"], {"ok": True}, {}, 10,
        output={"channels": [{"id": "C1", "name": "general"}]},
    )
    assert repository.sync_conversation_workflow_outcome(
        revision["workflow_revision_id"], "org:1", {"status": "complete"}, 10
    )
    conversation = store.get(intake["conversation_id"], "org:1", "user:1")
    assert conversation["status"] == "resolving"
    resumed = service.resume_resolved_slack_turn(conversation)
    assert resumed["state"] == "awaiting_approval"
    assert resumed["draft"]["destination_label"] == "#general"
    assert resumed["draft"]["text"] == "Hola equipo"


def test_public_channel_clarification_creates_authorized_listing_workflow(tmp_path):
    from libs.integrations.catalog import slack_definitions
    class Connections:
        def list_tenant_installations(self, tenant, provider):
            return [{"connection_id": "conn:s", "team_name": "Acme",
                     "status": "connected", "credential_version": 1,
                     "granted_scopes": ["channels:read"],
                     "enabled_capabilities": ["slack.channels.list"]}]
    repository = WorkflowRepository(str(tmp_path / "channel-list.db"))
    store = ConciergeConversationStore(repository, clock=lambda: 10)
    service = DynamicWorkflowService(
        object(), slack_definitions(), Connections(), repository,
        conversation_store=store, clock=lambda: 10, shadow_mode=False,
    )
    first = service.coordinate_slack_turn("org:1", "user:1", "Slack")
    second = service.coordinate_slack_turn(
        "org:1", "user:1", "sí, tengo canales públicos",
        conversation_id=first["conversation_id"],
    )

    result = service.advance_slack_turn(
        first["conversation_id"], "org:1", "user:1",
        "sí, tengo canales públicos", second,
    )

    assert result["state"] == "retrieving"
    revision = repository.get_revision_by_id(
        result["workflow"]["revisionId"], "org:1"
    )
    assert revision["steps"][0]["capability_id"] == "slack.channels.list"


def test_completed_read_presentation_is_generated_once_across_polls(tmp_path):
    class Connections:
        def list_installations(self, tenant, principal):
            return []
    repository = WorkflowRepository(str(tmp_path / "w.db"))
    store = ConciergeConversationStore(repository, clock=lambda: 100)
    store.create("org:1", "user:1", "conversation:1")
    service = DynamicWorkflowService(
        object(), [], Connections(), repository, conversation_store=store,
    )
    class Presenter:
        def __init__(self): self.calls = 0
        def present(self, question, evidence, locale):
            self.calls += 1
            return {"locale": locale, "answer": "grounded", "citations": [],
                    "partial": False}
    presenter = Presenter()
    first = service.present_read_once(
        "conversation:1", "org:1", "user:1", presenter,
        "question", {"messages": []}, "en",
    )
    second = service.present_read_once(
        "conversation:1", "org:1", "user:1", presenter,
        "question", {"messages": [{"text": "changed"}]}, "en",
    )
    assert first == second
    assert presenter.calls == 1


def test_changed_slack_draft_invalidates_prior_approval(tmp_path):
    from agents.orchestrator.conversation_state import ConciergeConversationStore
    from libs.integrations.catalog import slack_definitions
    class Connections:
        def list_tenant_installations(self, tenant, provider):
            return [{
                "connection_id": "conn:s", "team_name": "Acme", "status": "connected",
                "credential_version": 3, "granted_scopes": ["chat:write"],
                "enabled_capabilities": ["slack.message.send"],
            }]
    repository = WorkflowRepository(str(tmp_path / "w.db"))
    store = ConciergeConversationStore(repository, clock=lambda: 10)
    store.create("org:1", "user:1", "conversation:1")
    store.update("conversation:1", "org:1", "user:1",
                 active_connection={"id": "conn:s", "label": "Acme"},
                 active_channel={"id": "C1", "name": "general"})
    service = DynamicWorkflowService(
        object(), slack_definitions(), Connections(), repository,
        conversation_store=store, clock=lambda: 10,
    )
    first = service.materialize_slack_write(
        "conversation:1", "org:1", "user:1", "slack.message.send", "Hola"
    )
    service.approve_slack_draft(
        "conversation:1", "org:1", "user:1", first["draft_hash"]
    )
    second = service.materialize_slack_write(
        "conversation:1", "org:1", "user:1", "slack.message.send", "Hola equipo"
    )
    with pytest.raises(ValueError, match="draft binding changed"):
        service.approve_slack_draft(
            "conversation:1", "org:1", "user:1", first["draft_hash"]
        )
    assert not repository.is_revision_approved(
        second["workflow_run_id"], second["workflow_revision_id"],
        "org:1", second["plan_graph_hash"], 10,
    )
    store.update("conversation:1", "org:1", "user:1",
                 active_channel={"id": "C2", "name": "other"})
    with pytest.raises(ValueError, match="draft binding changed"):
        service.approve_slack_draft(
            "conversation:1", "org:1", "user:1", second["draft_hash"]
        )


def test_thread_and_dm_drafts_materialize_exact_targets_and_localized_success(tmp_path):
    from agents.orchestrator.conversation_state import ConciergeConversationStore
    from libs.integrations.catalog import slack_definitions
    class Connections:
        def list_tenant_installations(self, tenant, provider):
            return [{"connection_id": "conn:s", "team_name": "Acme", "status": "connected",
                     "credential_version": 1, "granted_scopes": ["chat:write", "im:write"],
                     "enabled_capabilities": ["slack.thread.reply", "slack.direct_message.send"]}]
    repository = WorkflowRepository(str(tmp_path / "w.db"))
    store = ConciergeConversationStore(repository, clock=lambda: 10)
    store.create("org:1", "user:1", "conversation:1")
    store.update("conversation:1", "org:1", "user:1",
                 active_connection={"id": "conn:s", "label": "Acme"},
                 active_channel={"id": "C1", "name": "general"},
                 active_thread={"channel_id": "C1", "thread_ts": "1.0"})
    service = DynamicWorkflowService(object(), slack_definitions(), Connections(), repository,
                                     conversation_store=store, clock=lambda: 10)
    reply = service.materialize_slack_write(
        "conversation:1", "org:1", "user:1", "slack.thread.reply", "De acuerdo"
    )
    step = repository.get_revision(reply["workflow_run_id"], reply["workflow_revision_id"], "org:1")["steps"][0]
    assert step["input"] == {"channel_id": "C1", "thread_ts": "1.0", "text": "De acuerdo"}

    store.update("conversation:1", "org:1", "user:1",
                 active_person={"id": "U1", "display_name": "María"})
    dm = service.materialize_slack_write(
        "conversation:1", "org:1", "user:1", "slack.direct_message.send", "Hola"
    )
    step = repository.get_revision(dm["workflow_run_id"], dm["workflow_revision_id"], "org:1")["steps"][0]
    assert step["input"] == {"user_id": "U1", "text": "Hola"}
    assert dm["destination_label"] == "María"
    assert service.complete_slack_write(
        "conversation:1", "org:1", "user:1", "es"
    )["answer"] == "Mensaje enviado"
    state = store.get("conversation:1", "org:1", "user:1")
    assert state.get("pending_draft") is None
    assert state["status"] == "succeeded"


class _ResolverConnections:
    def list_tenant_installations(self, tenant, provider):
        return [{"connection_id": "conn:s", "team_name": "Acme",
                 "status": "connected", "credential_version": 1,
                 "granted_scopes": ["channels:read", "chat:write"],
                 "enabled_capabilities": [
                     "slack.channels.list", "slack.message.send"]}]


def _finish_resolver_page(repository, revision_id, output, now=10):
    revision = repository.get_revision_by_id(revision_id, "org:1")
    claim = repository.claim_ready_step(
        revision["workflow_run_id"], revision["workflow_revision_id"],
        "org:1", "worker:1", now, 30,
    )
    repository.persist_completion(
        revision["workflow_revision_id"], "resolve-slack-channel", "org:1",
        claim["attempt"], {"ok": True}, {}, now, output=output,
    )
    return repository.sync_conversation_workflow_outcome(
        revision["workflow_revision_id"], "org:1", {"status": "complete"}, now
    )


def test_resolution_pages_durably_across_restart_and_finishes_from_its_event(tmp_path):
    from libs.integrations.catalog import slack_definitions

    database = str(tmp_path / "paged-resolver.db")
    repository = WorkflowRepository(database)
    store = ConciergeConversationStore(repository, clock=lambda: 10)
    service = DynamicWorkflowService(
        object(), slack_definitions(), _ResolverConnections(), repository,
        conversation_store=store, clock=lambda: 10,
    )
    intake = service.coordinate_slack_turn(
        "org:1", "user:1", "Manda en #general que Hola equipo"
    )
    resolving = service.advance_slack_turn(
        intake["conversation_id"], "org:1", "user:1",
        "Manda en #general que Hola equipo", intake,
    )
    conversation_id = intake["conversation_id"]
    resolver_run_id = store.get(
        conversation_id, "org:1", "user:1"
    )["resolution_request"]["resolver_run_id"]

    _finish_resolver_page(repository, resolving["workflow"]["revisionId"], {
        "channels": [{"id": "C9", "name": "otros"}],
        "response_metadata": {"next_cursor": "page-2"},
    })

    assert store.get(conversation_id, "org:1", "user:1")["status"] == "retrieving"
    after_page_one = repository.get_slack_resolver_run(resolver_run_id, "org:1")
    assert after_page_one["pages_processed"] == 1
    assert after_page_one["cursor"]["next"] == "page-2"
    assert after_page_one["status"] == "running"

    restarted = WorkflowRepository(database)
    restarted_store = ConciergeConversationStore(restarted, clock=lambda: 11)
    restarted_service = DynamicWorkflowService(
        object(), slack_definitions(), _ResolverConnections(), restarted,
        conversation_store=restarted_store, clock=lambda: 11,
    )
    resumable = restarted.list_resumable_slack_resolver_runs(11)
    assert [item["resolver_run_id"] for item in resumable] == [resolver_run_id]
    assert restarted_service.continue_slack_resolver_run(resumable[0], 11) is True
    assert restarted_service.continue_slack_resolver_run(
        restarted.get_slack_resolver_run(resolver_run_id, "org:1"), 11
    ) is False

    second_revision = restarted_store.get(
        conversation_id, "org:1", "user:1"
    )["workflow_revision_id"]
    page_two = restarted.get_revision_by_id(second_revision, "org:1")
    assert page_two["steps"][0]["input"]["cursor"] == "page-2"

    _finish_resolver_page(restarted, second_revision, {
        "channels": [{"id": "C1", "name": "general"}],
    }, now=11)

    completed = restarted.get_slack_resolver_run(resolver_run_id, "org:1")
    assert completed["status"] == "completed"
    assert completed["pages_processed"] == 2
    assert completed["outcome"]["entity"] == {"id": "C1", "name": "general"}
    assert restarted.count_outbox_events(
        "org:1", "slack-resolver:%s" % resolver_run_id
    ) == 1
    assert restarted_store.get(
        conversation_id, "org:1", "user:1"
    )["status"] == "resolving"

    payload = {"resolver_run_id": resolver_run_id, "principal_id": "user:1"}
    assert restarted_service.apply_slack_resolver_completion(
        "org:1", conversation_id, payload, 11,
    ) is True
    assert restarted_service.apply_slack_resolver_completion(
        "org:1", conversation_id, payload, 11,
    ) is False
    assert restarted_service.apply_slack_resolver_completion(
        "org:other", conversation_id, payload, 11,
    ) is False

    finished = restarted_store.get(conversation_id, "org:1", "user:1")
    assert finished["status"] == "awaiting_approval"
    assert finished["pending_draft"]["destination_label"] == "#general"
    assert finished["pending_draft"]["text"] == "Hola equipo"
    assert finished.get("resolution_request") is None


def test_outcome_events_track_the_whole_write_lifecycle_without_content(tmp_path):
    from libs.integrations.catalog import slack_definitions

    repository = WorkflowRepository(str(tmp_path / "outcome-lifecycle.db"))
    store = ConciergeConversationStore(repository, clock=lambda: 10)
    service = DynamicWorkflowService(
        object(), slack_definitions(), _ResolverConnections(), repository,
        conversation_store=store, clock=lambda: 10, slack_writes_enabled=True,
    )
    intake = service.coordinate_slack_turn(
        "org:1", "user:1", "Manda en #general que Hola equipo",
        channels=[{"id": "C1", "name": "general"}],
    )
    conversation_id = intake["conversation_id"]
    previewed = service.advance_slack_turn(
        conversation_id, "org:1", "user:1",
        "Manda en #general que Hola equipo", intake,
    )
    service.approve_slack_draft(
        conversation_id, "org:1", "user:1", previewed["draft"]["draft_hash"]
    )
    service.complete_slack_write(conversation_id, "org:1", "user:1")

    events = repository.list_conversation_outcome_events(
        conversation_id, "org:1", "user:1"
    )

    assert [item["event_type"] for item in events] == [
        "operation_attempted", "previewed", "approved", "completed",
    ]
    assert [item["event_sequence"] for item in events] == [1, 2, 3, 4]
    assert {item["operation_family"] for item in events} == {"post"}
    assert events[-1]["metrics"]["terminal_outcome"] == "sent"
    assert "Hola equipo" not in str(events)
    assert "C1" not in str(events)
    assert repository.conversation_outcome_baseline("org:1", 10, 11) == [
        {"event_type": event_type, "operation_family": "post",
         "total": 1, "conversations": 1}
        for event_type in (
            "approved", "completed", "operation_attempted", "previewed",
        )
    ]


def test_closing_a_previewed_conversation_records_an_explicit_rejection(tmp_path):
    from libs.integrations.catalog import slack_definitions

    repository = WorkflowRepository(str(tmp_path / "outcome-rejected.db"))
    store = ConciergeConversationStore(repository, clock=lambda: 10)
    service = DynamicWorkflowService(
        object(), slack_definitions(), _ResolverConnections(), repository,
        conversation_store=store, clock=lambda: 10, slack_writes_enabled=True,
    )
    intake = service.coordinate_slack_turn(
        "org:1", "user:1", "Manda en #general que Hola equipo",
        channels=[{"id": "C1", "name": "general"}],
    )
    conversation_id = intake["conversation_id"]
    service.advance_slack_turn(
        conversation_id, "org:1", "user:1",
        "Manda en #general que Hola equipo", intake,
    )

    assert store.close(conversation_id, "org:1", "user:1") is True
    assert store.close(conversation_id, "org:1", "user:1") is False

    events = repository.list_conversation_outcome_events(
        conversation_id, "org:1", "user:1"
    )
    assert [item["event_type"] for item in events][-1] == "rejected"
    assert events[-1]["operation_family"] == "post"
    assert events[-1]["metrics"]["terminal_outcome"] == "closed_by_user"


class _ExplodingBrain:
    """Any planner call during a grounded read is a regression."""

    def generate_plan(self, *args, **kwargs):
        raise AssertionError("a grounded read must not call the planner brain")

    def understand_slack(self, *args, **kwargs):
        raise AssertionError("no interpretation is needed for this fixture")


class _ReadConnections:
    def list_tenant_installations(self, tenant, provider):
        return [{"connection_id": "conn:s", "team_id": "T1", "team_name": "Acme",
                 "status": "connected", "credential_version": 1,
                 "granted_scopes": ["channels:read", "channels:history"],
                 "enabled_capabilities": [
                     "slack.channels.list", "slack.conversation.read",
                     "slack.thread.read"]}]


def _read_service(tmp_path, name):
    repository = WorkflowRepository(str(tmp_path / name))
    store = ConciergeConversationStore(repository, clock=lambda: 1_000_000)
    service = DynamicWorkflowService(
        _ExplodingBrain(), slack_definitions(), _ReadConnections(), repository,
        conversation_store=store, clock=lambda: 1_000_000,
    )
    return repository, store, service


def test_a_grounded_read_compiles_without_the_planner_brain(tmp_path):
    repository, store, service = _read_service(tmp_path, "read-direct.db")

    run, revision = service._dispatch_slack_read(
        "org:1", "user:1", "read",
        {"active_connection": {"id": "conn:s"},
         "active_channel": {"id": "C1", "name": "general"}},
    )

    step = repository.get_revision(
        run["workflow_run_id"], revision["workflow_revision_id"], "org:1"
    )["steps"][0]
    assert step["capability_id"] == "slack.conversation.read"
    assert step["effect"] == "read"
    assert step["input"]["channel_id"] == "C1"
    assert int(step["input"]["latest"]) == 1_000_000
    assert int(step["input"]["oldest"]) == 1_000_000 - 7 * 86400
    assert repository.revision_authorization_mode(
        run["workflow_run_id"], revision["workflow_revision_id"], "org:1",
        revision["plan_graph_hash"], 1_000_000,
    ) == "requested_read"


def test_an_explicit_period_replaces_the_disclosed_default(tmp_path):
    _, _, service = _read_service(tmp_path, "read-period.db")

    _, revision = service._dispatch_slack_read(
        "org:1", "user:1", "summarize",
        {"active_connection": {"id": "conn:s"},
         "active_channel": {"id": "C1"},
         "read_period": {"days": 2, "defaulted": False}},
    )

    step = revision["steps"][0]
    assert int(step["input"]["latest"]) - int(step["input"]["oldest"]) == 2 * 86400


def test_a_thread_context_reads_the_thread_not_the_channel(tmp_path):
    _, _, service = _read_service(tmp_path, "read-thread.db")

    _, revision = service._dispatch_slack_read(
        "org:1", "user:1", "read",
        {"active_connection": {"id": "conn:s"},
         "active_channel": {"id": "C1"},
         "active_thread": {"channel_id": "C1", "thread_ts": "1710.0001"}},
    )

    step = revision["steps"][0]
    assert step["capability_id"] == "slack.thread.read"
    assert step["input"]["thread_ts"] == "1710.0001"
    assert step["input"]["channel_id"] == "C1"


def test_listing_channels_needs_no_channel_and_no_period(tmp_path):
    _, _, service = _read_service(tmp_path, "read-list.db")

    _, revision = service._dispatch_slack_read(
        "org:1", "user:1", "list_channels",
        {"active_connection": {"id": "conn:s"}},
    )

    step = revision["steps"][0]
    assert step["capability_id"] == "slack.channels.list"
    assert step["input"] == {"limit": 200}
    _assert_matches_capability_schema(step)


def test_a_read_without_scope_or_target_fails_closed(tmp_path):
    _, _, service = _read_service(tmp_path, "read-denied.db")

    with pytest.raises(ValueError, match="Slack read target is unresolved"):
        service._dispatch_slack_read(
            "org:1", "user:1", "read", {"active_connection": {"id": "conn:s"}},
        )
    with pytest.raises(PermissionError, match="missing_scope"):
        service._dispatch_slack_read(
            "org:1", "user:1", "list_private_channels",
            {"active_connection": {"id": "conn:s"}},
        )


def _assert_matches_capability_schema(step):
    """Every compiled read must satisfy the descriptor the broker enforces."""
    import jsonschema

    definition = next(
        item for item in slack_definitions()
        if item.capability_id == step["capability_id"]
    )
    jsonschema.validate(step["input"], definition.input_schema)


@pytest.mark.parametrize("operation,resolved", [
    ("read", {"active_connection": {"id": "conn:s"},
              "active_channel": {"id": "C1"}}),
    ("summarize", {"active_connection": {"id": "conn:s"},
                   "active_channel": {"id": "C1"},
                   "read_period": {"days": 30}}),
    ("read", {"active_connection": {"id": "conn:s"},
              "active_channel": {"id": "C1"},
              "active_thread": {"channel_id": "C1", "thread_ts": "1710.1"}}),
    ("list_channels", {"active_connection": {"id": "conn:s"}}),
])
def test_every_compiled_read_satisfies_its_capability_schema(
    tmp_path, operation, resolved,
):
    _, _, service = _read_service(tmp_path, "read-schema-%s.db" % operation)

    _, revision = service._dispatch_slack_read(
        "org:1", "user:1", operation, resolved,
    )

    _assert_matches_capability_schema(revision["steps"][0])


def test_a_message_read_fetches_the_directory_beside_it(tmp_path):
    repository = WorkflowRepository(str(tmp_path / "read-directory.db"))
    store = ConciergeConversationStore(repository, clock=lambda: 1_000_000)

    class Connections:
        def list_tenant_installations(self, tenant, provider):
            return [{"connection_id": "conn:s", "status": "connected",
                     "credential_version": 1,
                     "granted_scopes": ["channels:read", "channels:history",
                                        "users:read"],
                     "enabled_capabilities": [
                         "slack.channels.list", "slack.conversation.read",
                         "slack.users.list"]}]

    service = DynamicWorkflowService(
        _ExplodingBrain(), slack_definitions(), Connections(), repository,
        conversation_store=store, clock=lambda: 1_000_000,
    )

    _, revision = service._dispatch_slack_read(
        "org:1", "user:1", "read",
        {"active_connection": {"id": "conn:s"}, "active_channel": {"id": "C1"}},
    )
    _, listing = service._dispatch_slack_read(
        "org:1", "user:1", "list_channels", {"active_connection": {"id": "conn:s"}},
    )

    assert [step["capability_id"] for step in revision["steps"]] == [
        "slack.conversation.read", "slack.users.list",
    ]
    assert all(step["depends_on"] == [] for step in revision["steps"])
    for step in revision["steps"]:
        _assert_matches_capability_schema(step)
    # A channel listing has no authors to name, so it stays a single call.
    assert [step["capability_id"] for step in listing["steps"]] == [
        "slack.channels.list",
    ]


def test_a_read_without_directory_scope_still_compiles(tmp_path):
    _, _, service = _read_service(tmp_path, "read-no-directory.db")

    _, revision = service._dispatch_slack_read(
        "org:1", "user:1", "read",
        {"active_connection": {"id": "conn:s"}, "active_channel": {"id": "C1"}},
    )

    assert [step["capability_id"] for step in revision["steps"]] == [
        "slack.conversation.read",
    ]
