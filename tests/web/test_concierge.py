from web.concierge import (
    _classified_recovery, _conversation_response, _is_slack_turn,
    _slack_turn_text, _tenant_resolver, _turn_response,
)


def test_explicit_local_tenant_fallback_survives_principal_rotation(monkeypatch):
    monkeypatch.setenv("TESSERA_PRINCIPAL_TENANTS_JSON", "{}")
    monkeypatch.setenv("TESSERA_LOCAL_TENANT_ID", "org:local")

    assert _tenant_resolver()("new-principal") == "org:local"


def test_natural_channel_message_is_routed_to_typed_slack_conversation():
    assert _is_slack_turn("envía un mensaje al canal tessera-test")
    assert _is_slack_turn("quiero publicar en el canal general")


def test_slack_followup_recovers_channel_and_message_from_user_history():
    history = [
        {"role": "user", "text": "quiero enviar algo por Slack"},
        {"role": "concierge", "text": "¿En qué canal?"},
        {"role": "user", "text": "en el canal tessera-test"},
        {"role": "concierge", "text": "¿Cuál mensaje?"},
        {"role": "user", "text": "que diga estoy aquí, ¿quién es?"},
    ]

    recovered = _slack_turn_text("sí, mándalo", history, None)

    assert _is_slack_turn(recovered)
    assert "canal tessera-test" in recovered
    assert "que diga estoy aquí" in recovered


def test_slack_history_preserves_exact_quoted_message_through_confirmation():
    from agents.orchestrator.slack_conversation import interpret_slack_turn

    history = [
        {"role": "user", "text": "quiero enviar un mensaje por Slack"},
        {"role": "user", "text": "en el canal tessera-test"},
        {"role": "user", "text": 'mándame el mensaje que diga "estoy aquí, ¿quién es?"'},
    ]

    recovered = _slack_turn_text("sí, mándalo", history, None)
    turn = interpret_slack_turn(recovered)

    assert turn.operation == "post"
    assert turn.channel_name == "tessera-test"
    assert turn.message_text == "estoy aquí, ¿quién es?"


def test_orphan_resolving_conversation_becomes_actionable_need():
    from web.concierge import _conversation_response

    response = _conversation_response({
        "conversation_id": "conversation:orphan",
        "status": "resolving",
        "workflow_run_id": None,
        "workflow_revision_id": None,
    })

    assert response["state"] == "needs_input"
    assert response["need"]["field"] == "operation"


def test_needs_input_contract_has_one_question_and_opaque_conversation_id():
    response = _turn_response({
        "state": "needs_input", "conversation_id": "conversation:1",
        "need": {"field": "message_text", "question": "¿Qué mensaje quieres enviar?"},
        "resolved": {"active_channel": {"id": "C-secret"}},
    })
    assert response == {
        "state": "needs_input", "conversationId": "conversation:1",
        "need": {"field": "message_text", "question": "¿Qué mensaje quieres enviar?"},
    }
    assert "C-secret" not in str(response)


def test_poll_contract_returns_grounded_answer_and_safe_exact_draft():
    completed = _conversation_response({
        "status": "ready", "conversation_id": "conversation:1",
        "presentation": {"answer": "Resumen", "citations": [{"permalink": "https://slack/source"}], "partial": True,
                         "period": {"oldest": "1", "latest": "2"},
                         "partial_reason": "rate_limit"},
        "workflow_run_id": "workflow:1", "workflow_revision_id": "revision:1",
    })
    assert completed["answer"] == "Resumen"
    assert completed["citations"] == [{"permalink": "https://slack/source"}]
    assert completed["period"] == {"oldest": "1", "latest": "2"}
    assert completed["partialReason"] == "rate_limit"
    draft = _conversation_response({
        "status": "awaiting_approval", "conversation_id": "conversation:2",
        "pending_draft": {"draft_hash": "hash", "destination_label": "#general",
                          "text": "Hola", "workflow_run_id": "workflow:2",
                          "workflow_revision_id": "revision:2", "channel_id": "C-secret"},
    })
    assert draft["draft"]["destination"] == "#general"
    assert draft["draft"]["text"] == "Hola"
    assert "C-secret" not in str(draft)


def test_known_recovery_is_structured_and_redacts_exception_details():
    response = _classified_recovery(
        PermissionError("missing_scope:users:read xoxb-secret"), "conversation:1"
    )
    assert response["error"] == {"code": "missing_scope"}
    assert response["recovery"] == {"action": "upgrade_scopes"}
    assert "xoxb" not in str(response)
