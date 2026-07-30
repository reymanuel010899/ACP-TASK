import pytest

from agents.orchestrator.conversation_state import ConciergeConversationStore
from agents.orchestrator.workflow_repository import WorkflowRepository


class Clock:
    def __init__(self, value=100):
        self.value = value

    def __call__(self):
        return self.value


def _store(tmp_path, clock=None, crypto=None):
    repository = WorkflowRepository(
        str(tmp_path / "workflows.sqlite3"), content_crypto=crypto
    )
    return ConciergeConversationStore(repository, clock or Clock(), ttl_seconds=180)


def test_answer_clears_one_need_and_retains_resolved_channel(tmp_path):
    store = _store(tmp_path)
    created = store.create("org:acme", "user:alice", "conversation:1", "es")
    assert created["status"] == "interpreting"
    store.update(
        "conversation:1", "org:acme", "user:alice",
        active_channel={"id": "C1", "name": "nuevo-canal"},
    )
    store.record_need(
        "conversation:1", "org:acme", "user:alice",
        {"kind": "missing", "field": "message_text", "question": "¿Qué mensaje?"},
    )

    answer = store.answer(
        "conversation:1", "org:acme", "user:alice", "turn:2",
        "message_text", "Hola equipo",
    )

    state = answer["conversation"]
    assert state["active_channel"] == {"id": "C1", "name": "nuevo-canal"}
    assert state["known_inputs"] == {"message_text": "Hola equipo"}
    assert state.get("blocking_need") is None
    assert state["status"] == "interpreting"


def test_conversation_is_bound_to_both_tenant_and_principal(tmp_path):
    store = _store(tmp_path)
    store.create("org:acme", "user:alice", "conversation:secret")
    store.update(
        "conversation:secret", "org:acme", "user:alice",
        active_person={"id": "U1"},
    )

    assert store.get("conversation:secret", "org:acme", "user:bob") is None
    assert store.get("conversation:secret", "org:other", "user:alice") is None
    with pytest.raises(KeyError, match="unavailable"):
        store.update(
            "conversation:secret", "org:acme", "user:bob", locale="en"
        )
    with pytest.raises(KeyError, match="unavailable"):
        store.answer(
            "conversation:secret", "org:other", "user:alice", "answer:1",
            "message_text", "leak",
        )

    with pytest.raises(ValueError, match="invalid conversation status"):
        store.update(
            "conversation:secret", "org:acme", "user:alice", status="invented"
        )


@pytest.mark.parametrize("terminal", ["expired", "closed"])
def test_terminal_conversation_cannot_supply_context_to_later_turn(
    tmp_path, terminal
):
    clock = Clock()
    store = _store(tmp_path, clock)
    store.create("org:acme", "user:alice", "conversation:old")
    store.update(
        "conversation:old", "org:acme", "user:alice",
        active_channel={"id": "C1"}, active_person={"id": "U1"},
        active_thread={"channel_id": "C1", "thread_ts": "1.0"},
        pending_draft={"destination_hash": "d", "payload_hash": "p"},
    )
    if terminal == "closed":
        assert store.close("conversation:old", "org:acme", "user:alice")
    else:
        clock.value = 281

    assert store.get("conversation:old", "org:acme", "user:alice") is None
    audit = store.get(
        "conversation:old", "org:acme", "user:alice", include_terminal=True
    )
    assert audit["status"] == terminal
    assert "active_channel" not in audit
    assert "active_person" not in audit
    assert "active_thread" not in audit
    assert "pending_draft" not in audit


def test_answer_idempotency_reuses_workflow_pointer(tmp_path):
    store = _store(tmp_path)
    store.create("org:acme", "user:alice", "conversation:1")
    store.record_need(
        "conversation:1", "org:acme", "user:alice",
        {"kind": "missing", "field": "message_text", "question": "Text?"},
    )
    first = store.answer(
        "conversation:1", "org:acme", "user:alice", "answer:stable",
        "message_text", "Hello", "workflow:1", "revision:1",
    )
    second = store.answer(
        "conversation:1", "org:acme", "user:alice", "answer:stable",
        "message_text", "Hello", "workflow:ignored", "revision:ignored",
    )

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["workflow_run_id"] == "workflow:1"
    assert second["workflow_revision_id"] == "revision:1"
    rows = store.repository._connection.execute(
        "SELECT count(*) AS count FROM concierge_answers"
    ).fetchone()
    assert rows["count"] == 1
    with pytest.raises(ValueError, match="different answer"):
        store.answer(
            "conversation:1", "org:acme", "user:alice", "answer:stable",
            "message_text", "Changed",
        )


class ContentCrypto:
    def __init__(self):
        self.values = {}

    def seal(self, value, context):
        token = "sealed:%d" % len(self.values)
        self.values[token] = value
        return {"ciphertext": token, "context": context}

    def open(self, envelope, context):
        assert envelope["context"] == context
        return self.values[envelope["ciphertext"]]


def test_presentation_is_encrypted_then_purged_but_hash_remains(tmp_path):
    clock = Clock()
    store = _store(tmp_path, clock, ContentCrypto())
    store.create("org:acme", "user:alice", "conversation:1")
    stored = store.present(
        "conversation:1", "org:acme", "user:alice",
        {"locale": "es", "answer": "contenido privado", "citations": []},
    )
    raw = store.repository._connection.execute(
        "SELECT presentation_json FROM concierge_conversations"
    ).fetchone()["presentation_json"]
    assert "contenido privado" not in raw
    assert stored["presentation"]["answer"] == "contenido privado"
    presentation_hash = stored["presentation_hash"]

    clock.value = 281
    assert store.purge_expired_content() == 1
    audit = store.get(
        "conversation:1", "org:acme", "user:alice", include_terminal=True
    )
    assert audit["presentation"] is None
    assert audit["presentation_hash"] == presentation_hash
