"""Deterministic multi-turn agent-needs loop coverage (U19)."""

import pytest

from agents.orchestrator.conversation_state import ConversationStateStore
from libs.protocol import TASK_NEEDS_INPUT, TASK_NEEDS_PERMISSION


def _need(**overrides):
    value = {
        "type": TASK_NEEDS_INPUT,
        "task_id": "task-1",
        "conversation_id": "conversation-1",
        "reason": "I need the meeting details",
        "blocking": True,
        "missing_fields": ["start_time", "duration", "contact"],
        "input_schema": {"type": "object"},
    }
    value.update(overrides)
    return value


def test_resolves_authorized_contact_and_preference_then_asks_only_for_time(
    tmp_path,
):
    store = ConversationStateStore(str(tmp_path / "conversation.sqlite"))
    store.create_task(
        "task-1",
        "agent:calendar",
        "calendar.create",
        conversation_id="conversation-1",
        preferences={"duration": 30},
        permissions={"contacts.read": True},
    )

    resolution = store.resolve_need(
        "task-1",
        _need(),
        authorized_data={"contact": "ada@example.test"},
    )

    assert resolution["status"] == "needs_input"
    assert resolution["resolved_fields"] == {
        "duration": 30,
        "contact": "ada@example.test",
    }
    assert resolution["unresolved_fields"] == ["start_time"]
    assert resolution["question"] == "¿Qué hora de inicio prefieres?"

    resolution = store.resolve_need(
        "task-1",
        _need(),
        conversation={"start_time": "11:00"},
        authorized_data={"contact": "ada@example.test"},
    )
    assert resolution["status"] == "resolved"
    state = store.get_task("task-1")
    assert state["agent_id"] == "agent:calendar"
    assert state["capability"] == "calendar.create"
    assert state["known_inputs"]["start_time"] == "11:00"
    assert state["permissions"] == {"contacts.read": True}
    assert state["unresolved_needs"] == []


def test_ambiguous_contact_is_asked_as_one_natural_choice(tmp_path):
    store = ConversationStateStore(str(tmp_path / "conversation.sqlite"))
    store.create_task(
        "task-1",
        "agent:calendar",
        "calendar.create",
        conversation_id="conversation-1",
    )

    resolution = store.resolve_need(
        "task-1",
        _need(
            missing_fields=["contact"],
            options={"contact": ["Ana (trabajo)", "Ana (personal)"]},
        ),
    )

    assert resolution["status"] == "needs_input"
    assert resolution["question"] == (
        "¿Qué contacto prefieres: Ana (trabajo) o Ana (personal)?"
    )


def test_safe_default_requires_confirmation_and_question_is_user_facing(
    tmp_path,
):
    store = ConversationStateStore(str(tmp_path / "conversation.sqlite"))
    store.create_task(
        "task-1",
        "agent:calendar",
        "calendar.create",
        conversation_id="conversation-1",
    )

    resolution = store.resolve_need(
        "task-1",
        _need(
            missing_fields=["duration"],
            recommended_default={"duration": 30},
        ),
    )

    assert resolution["status"] == "needs_confirmation"
    assert resolution["question"] == "¿Confirmas una duración de 30?"
    assert "task_id" not in resolution["question"]
    assert "missing_fields" not in resolution["question"]


def test_persisted_known_input_is_not_asked_again(tmp_path):
    store = ConversationStateStore(str(tmp_path / "conversation.sqlite"))
    store.create_task(
        "task-1",
        "agent:calendar",
        "calendar.create",
        conversation_id="conversation-1",
        known_inputs={"start_time": "11:00"},
    )

    resolution = store.resolve_need(
        "task-1",
        _need(missing_fields=["start_time"]),
    )

    assert resolution == {
        "status": "resolved",
        "resolved_fields": {"start_time": "11:00"},
    }


def test_unauthorized_lookup_asks_permission_before_using_data(tmp_path):
    store = ConversationStateStore(str(tmp_path / "conversation.sqlite"))
    store.create_task(
        "task-1",
        "agent:calendar",
        "calendar.create",
        conversation_id="conversation-1",
    )
    need = _need(
        type=TASK_NEEDS_PERMISSION,
        permission="contacts.read",
        reason="find the invitee",
        missing_fields=None,
        input_schema=None,
    )

    resolution = store.resolve_need(
        "task-1",
        need,
        authorized_data={"contact": "must-not-be-used@example.test"},
    )

    assert resolution["status"] == "needs_permission"
    assert "contactos" in resolution["question"].lower()
    assert store.get_task("task-1")["known_inputs"] == {}


def test_continue_is_idempotent_and_correction_keeps_same_task_and_agent(
    tmp_path,
):
    sent = []

    def sender(agent_id, envelope):
        sent.append((agent_id, envelope))
        return {"type": "task.progress", "progress": 0.5}

    store = ConversationStateStore(str(tmp_path / "conversation.sqlite"))
    store.create_task(
        "task-1",
        "agent:calendar",
        "calendar.create",
        conversation_id="conversation-1",
        known_inputs={"start_time": "10:00"},
    )

    first = store.continue_task(
        "task-1", {"duration": 30}, sender=sender
    )
    duplicate = store.continue_task(
        "task-1", {"duration": 30}, sender=sender
    )
    correction = store.continue_task(
        "task-1", {"start_time": "11:00"}, sender=sender
    )

    assert duplicate == first
    assert len(sent) == 2
    assert {call[1]["task_id"] for call in sent} == {"task-1"}
    assert {call[0] for call in sent} == {"agent:calendar"}
    assert sent[1][1]["resolved_fields"] == {"start_time": "11:00"}
    assert sent[1][1]["type"] == "task.continue"
    state = store.get_task("task-1")
    assert state["known_inputs"]["start_time"] == "11:00"
    assert state["answers"]["start_time"] == "11:00"
    assert state["proposal"]["start_time"] == "11:00"


def test_task_context_survives_store_reopen(tmp_path):
    path = str(tmp_path / "conversation.sqlite")
    store = ConversationStateStore(path)
    store.create_task(
        "task-1",
        "agent:calendar",
        "calendar.create",
        conversation_id="conversation-1",
        known_inputs={"title": "Planning"},
        permissions={"contacts.read": True},
        answers={"duration": 30},
    )
    store.close()

    reopened = ConversationStateStore(path)
    state = reopened.get_task("task-1")
    assert state["task_id"] == "task-1"
    assert state["agent_id"] == "agent:calendar"
    assert state["capability"] == "calendar.create"
    assert state["known_inputs"] == {"title": "Planning"}
    assert state["permissions"] == {"contacts.read": True}
    assert state["answers"] == {"duration": 30}


def test_expired_conversation_closes_without_contacting_agent(tmp_path):
    now = [1000]
    store = ConversationStateStore(
        str(tmp_path / "conversation.sqlite"),
        clock=lambda: now[0],
        timeout_seconds=60,
    )
    store.create_task(
        "task-1",
        "agent:calendar",
        "calendar.create",
        conversation_id="conversation-1",
    )
    now[0] = 1061

    with pytest.raises(TimeoutError):
        store.continue_task(
            "task-1",
            {"start_time": "11:00"},
            sender=lambda *_: pytest.fail("expired task contacted agent"),
        )
    assert store.get_task("task-1", include_expired=True)["status"] == "expired"
    with pytest.raises(TimeoutError):
        store.create_task(
            "task-1",
            "agent:calendar",
            "calendar.create",
            conversation_id="conversation-1",
        )


def test_agent_failure_is_truthful_and_retryable_without_losing_answers(
    tmp_path,
):
    attempts = []

    def failing_sender(agent_id, envelope):
        attempts.append((agent_id, envelope))
        raise RuntimeError("provider unavailable")

    store = ConversationStateStore(str(tmp_path / "conversation.sqlite"))
    store.create_task(
        "task-1",
        "agent:calendar",
        "calendar.create",
        conversation_id="conversation-1",
    )

    result = store.continue_task(
        "task-1", {"start_time": "11:00"}, sender=failing_sender
    )

    assert result["status"] == "agent_unavailable"
    assert result["message"] == (
        "No pude continuar con el agente seleccionado. Puedes intentarlo de nuevo."
    )
    assert store.get_task("task-1")["answers"]["start_time"] == "11:00"
    assert len(attempts) == 1
