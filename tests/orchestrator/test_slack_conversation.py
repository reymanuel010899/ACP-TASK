from agents.orchestrator.slack_conversation import (
    SlackConversationCoordinator,
    interpret_slack_turn,
)
from agents.orchestrator.workflow_models import (
    SlackInterpretation,
    SlackInterpretationCorrection,
    SlackInterpretationSlot,
    SlackOperationCandidate,
    SlackOperationDependency,
)


def test_operation_clarification_understands_public_channel_listing():
    coordinator = SlackConversationCoordinator()
    installations = [{
        "connection_id": "conn:s", "team_name": "Acme", "status": "connected",
    }]
    first = coordinator.coordinate("Slack", installations=installations)
    active = {
        "operation": first.turn.operation,
        "locale": "es",
        "blocking_need": first.need,
        "active_connection": {"id": "conn:s", "label": "Acme"},
    }

    clarified = coordinator.coordinate(
        "sí, tengo canales públicos", active_state=active,
        installations=installations,
    )

    assert clarified.state == "resolving"
    assert clarified.turn.operation == "list_channels"
    assert clarified.need is None


def test_natural_spanish_slack_requests_do_not_repeat_generic_operation_need():
    coordinator = SlackConversationCoordinator()
    installations = [{
        "connection_id": "conn:s", "team_name": "Acme", "status": "connected",
    }]
    active = {
        "operation": "unsupported", "locale": "es",
        "blocking_need": {"kind": "missing", "field": "operation",
                          "question": "¿Qué quieres hacer en Slack?", "options": []},
        "active_connection": {"id": "conn:s", "label": "Acme"},
    }

    private = coordinator.coordinate(
        "saber cuántos canales privados tengo", active_state=active,
        installations=installations,
    )
    public = coordinator.coordinate(
        "cuántos canales públicos tenemos", active_state=active,
        installations=installations,
    )
    send = coordinator.coordinate(
        "enviar un mensaje", active_state=active, installations=installations,
    )

    assert private.turn.operation == "list_private_channels"
    assert private.state == "resolving"
    assert public.turn.operation == "list_channels"
    assert public.state == "resolving"
    assert send.turn.operation == "post"
    assert send.need["field"] == "channel"


def test_slack_access_question_answers_from_connected_installations():
    connected = SlackConversationCoordinator().coordinate(
        "¿Tienes acceso a Slack, sí o no?",
        installations=[{
            "connection_id": "conn:s", "team_name": "Airobotix",
            "status": "connected",
        }],
    )
    disconnected = SlackConversationCoordinator().coordinate(
        "Do you have access to Slack?", installations=[]
    )

    assert connected.state == "completed"
    assert connected.turn.operation == "status"
    assert connected.message == (
        "Sí. Tengo acceso a Slack mediante el workspace Airobotix."
    )
    assert disconnected.state == "completed"
    assert disconnected.message == "No. Slack is not connected."


def test_spanish_channel_name_without_hash_is_grounded_before_message_prompt():
    result = SlackConversationCoordinator().coordinate(
        "envía un mensaje al canal tessera-test",
        installations=[{"connection_id": "conn:s", "status": "connected"}],
        channels=[{"id": "C1", "name": "tessera-test"}],
    )

    assert result.turn.operation == "post"
    assert result.resolved["active_channel"] == {"id": "C1", "name": "tessera-test"}
    assert result.need["field"] == "message_text"


INSTALLATION = {
    "connection_id": "conn:slack", "team_id": "T1", "team_name": "Acme",
    "status": "connected",
}
CHANNEL = {"id": "C1", "name": "nuevo-canal", "is_private": False}


def test_post_retains_unique_channel_and_asks_only_for_message():
    result = SlackConversationCoordinator().coordinate(
        "Manda un mensaje en #nuevo-canal.", installations=[INSTALLATION],
        channels=[CHANNEL],
    )
    assert result.state == "needs_input"
    assert result.resolved["active_channel"]["id"] == "C1"
    assert result.need["field"] == "message_text"
    assert result.need["question"] == "¿Qué mensaje quieres enviar?"


def test_ambiguous_person_returns_safe_profiles_without_selecting_by_order():
    users = [
        {"id": "U1", "display_name": "María", "real_name": "María Uno", "handle": "maria1", "image_url": "https://img/1"},
        {"id": "U2", "display_name": "Maria", "real_name": "María Dos", "handle": "maria2", "image_url": "https://img/2"},
    ]
    result = SlackConversationCoordinator().coordinate(
        "Mándale a María que sí", installations=[INSTALLATION], users=users,
    )
    assert result.need["field"] == "person"
    assert [item["id"] for item in result.need["options"]] == ["U1", "U2"]
    assert "active_person" not in result.resolved


def test_multiple_workspaces_are_resolved_before_same_channel_name():
    result = SlackConversationCoordinator().coordinate(
        "Lee #general", installations=[
            INSTALLATION,
            {"connection_id": "conn:two", "team_id": "T2", "status": "connected"},
        ], channels=[{"id": "C1", "name": "general"}],
    )
    assert result.need["field"] == "workspace"
    assert "active_channel" not in result.resolved


def test_read_without_channel_never_becomes_global_search():
    result = SlackConversationCoordinator().coordinate(
        "¿Qué dijo María?", installations=[INSTALLATION],
        users=[{"id": "U1", "display_name": "María"}],
    )
    assert result.turn.operation == "read"
    assert result.need["field"] == "channel"


def test_english_turn_preserves_spanish_channel_and_locale():
    result = SlackConversationCoordinator().coordinate(
        "What did María write in #canal-espanol?", installations=[INSTALLATION],
        channels=[{"id": "C2", "name": "canal-espanol"}],
        users=[{"id": "U1", "display_name": "María"}],
    )
    assert result.turn.locale == "en"
    assert result.resolved["active_channel"]["name"] == "canal-espanol"
    assert result.resolved["read_period"] == {"days": 7, "defaulted": True}


def test_offline_parser_supports_common_bilingual_subset():
    cases = {
        "post in #general: hello": ("post", "en"),
        "Manda un mensaje en #general": ("post", "es"),
        "Reply there that I agree": ("reply", "en"),
        "Respóndele ahí que estoy de acuerdo": ("reply", "es"),
        "Send a direct message to Maria saying hello": ("dm", "en"),
        "Mándale a María que hola": ("dm", "es"),
    }
    for text, expected in cases.items():
        turn = interpret_slack_turn(text)
        assert (turn.operation, turn.locale) == expected


def test_model_like_ids_have_no_place_in_typed_turn_contract():
    turn = interpret_slack_turn("Send a message in #general")
    assert "channel_id" not in turn.model_dump()
    assert "connection_id" not in turn.model_dump()
    assert "user_id" not in turn.model_dump()


def test_registry_interpretation_becomes_groundable_turn_and_keeps_compound_shape():
    interpretation = SlackInterpretation(
        operations=[
            SlackOperationCandidate(operation_id="slack.conversation.read", confidence=0.9),
            SlackOperationCandidate(operation_id="slack.message.send", confidence=0.9),
        ],
        slots=[
            SlackInterpretationSlot(name="channel", value="general", provenance="current_turn"),
            SlackInterpretationSlot(name="message", value="Hola", provenance="current_turn"),
        ],
        dependencies=[SlackOperationDependency(operation_index=1, depends_on_index=0)],
        locale="es", confidence=0.9,
    )
    result = SlackConversationCoordinator().coordinate(
        "lee y publica", interpretation=interpretation,
        installations=[INSTALLATION], channels=[{"id": "C1", "name": "general"}],
    )

    assert result.turn.operation == "read"
    assert result.resolved["active_channel"]["id"] == "C1"


def test_compound_slots_with_same_name_remain_attached_to_first_operation():
    interpretation = SlackInterpretation(
        operations=[
            SlackOperationCandidate(
                operation_id="slack.conversation.read", confidence=0.9,
            ),
            SlackOperationCandidate(
                operation_id="slack.message.send", confidence=0.9,
            ),
        ],
        slots=[
            SlackInterpretationSlot(
                name="channel", value="ventas", provenance="current_turn",
                operation_index=0,
            ),
            SlackInterpretationSlot(
                name="channel", value="leadership", provenance="current_turn",
                operation_index=1,
            ),
            SlackInterpretationSlot(
                name="message", value="Resumen listo", provenance="current_turn",
                operation_index=1,
            ),
        ],
        locale="es", confidence=0.9,
    )

    result = SlackConversationCoordinator().coordinate(
        "resume y publica", interpretation=interpretation,
        installations=[INSTALLATION],
        channels=[
            {"id": "C1", "name": "ventas"},
            {"id": "C2", "name": "leadership"},
        ],
    )

    assert result.resolved["active_channel"] == {"id": "C1", "name": "ventas"}


def test_channel_only_model_correction_preserves_resolved_message():
    interpretation = SlackInterpretation(
        operations=[SlackOperationCandidate(
            operation_id="slack.message.send", confidence=0.95,
        )],
        corrections=[SlackInterpretationCorrection(
            slot="channel", replacement="anuncios", provenance="current_turn",
        )],
        locale="es", confidence=0.95,
    )
    result = SlackConversationCoordinator().coordinate(
        "no, mejor anuncios", interpretation=interpretation,
        active_state={
            "operation": "post", "locale": "es",
            "active_connection": {"id": "conn:slack", "label": "Acme"},
            "active_channel": {"id": "C1", "name": "general"},
            "pending_draft": {"text": "Hola equipo"},
        },
        installations=[INSTALLATION],
        channels=[{"id": "C2", "name": "anuncios"}],
    )

    assert result.state == "resolving"
    assert result.resolved["active_channel"] == {"id": "C2", "name": "anuncios"}
    assert result.resolved["message_text"] == "Hola equipo"


def test_thread_shorthand_uses_only_server_grounded_context():
    result = SlackConversationCoordinator().coordinate(
        "respóndele ahí que recibido",
        active_state={
            "operation": "read", "locale": "es",
            "active_connection": {"id": "conn:slack", "label": "Acme"},
            "active_channel": {"id": "C1", "name": "general"},
            "active_thread": {
                "channel_id": "C1", "thread_ts": "1710000000.000100",
            },
        },
        installations=[INSTALLATION],
    )

    assert result.state == "resolving"
    assert result.turn.operation == "reply"
    assert result.resolved["active_thread"] == {
        "channel_id": "C1", "thread_ts": "1710000000.000100",
    }
    assert result.resolved["message_text"] == "recibido"


def test_blocking_message_answer_preserves_post_operation_and_channel():
    result = SlackConversationCoordinator().coordinate(
        "Hola equipo",
        active_state={
            "operation": "post", "locale": "es",
            "active_connection": {"id": "conn:s", "label": "Acme"},
            "active_channel": {"id": "C1", "name": "general"},
            "blocking_need": {"kind": "missing", "field": "message_text",
                              "question": "¿Qué mensaje?", "options": []},
        },
        installations=[{"connection_id": "conn:s", "status": "connected"}],
    )
    assert result.state == "resolving"
    assert result.turn.operation == "post"
    assert result.resolved["active_channel"]["id"] == "C1"
    assert result.resolved["message_text"] == "Hola equipo"


def test_blocking_person_selection_accepts_only_one_stored_candidate():
    active = {
        "operation": "dm", "locale": "es",
        "active_connection": {"id": "conn:s", "label": "Acme"},
        "blocking_need": {"kind": "selection", "field": "person",
                          "question": "¿Cuál María?", "options": [
            {"id": "U1", "display_name": "María", "handle": "maria.ops"},
            {"id": "U2", "display_name": "María", "handle": "maria.sales"},
        ]},
    }
    result = SlackConversationCoordinator().coordinate(
        "María · @maria.sales", active_state=active,
        installations=[{"connection_id": "conn:s", "status": "connected"}],
    )
    assert result.resolved["active_person"]["id"] == "U2"
