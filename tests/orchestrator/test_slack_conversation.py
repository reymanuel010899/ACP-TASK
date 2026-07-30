from agents.orchestrator.slack_conversation import (
    SlackConversationCoordinator,
    interpret_slack_turn,
)


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
