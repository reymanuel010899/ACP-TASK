from web.concierge import (
    _classified_recovery, _conversation_response, _turn_response,
)


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
        "presentation": {"answer": "Resumen", "citations": [{"permalink": "https://slack/source"}], "partial": True},
        "workflow_run_id": "workflow:1", "workflow_revision_id": "revision:1",
    })
    assert completed["answer"] == "Resumen"
    assert completed["citations"] == [{"permalink": "https://slack/source"}]
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
