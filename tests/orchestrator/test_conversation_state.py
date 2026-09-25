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


def test_turn_commit_is_versioned_idempotent_and_emits_one_outbox_event(tmp_path):
    store = _store(tmp_path)
    created = store.create("org:acme", "user:alice", "conversation:turn")
    assert created["state_version"] == 1

    started = store.begin_turn(
        "conversation:turn", "org:acme", "user:alice", "turn:client-1",
        expected_version=1, request={"text": "Send a Slack message"},
    )
    assert started["duplicate"] is False
    committed = store.commit_turn(
        "conversation:turn", "org:acme", "user:alice", "turn:client-1",
        expected_version=1,
        changes={
            "status": "needs_input",
            "operation": "post",
            "blocking_need": {
                "kind": "missing", "field": "channel",
                "question": "Which channel?",
            },
        },
        response={"state": "needs_input", "need": {"field": "channel"}},
    )

    assert committed["conversation"]["state_version"] == 2
    assert committed["conversation"]["operation"] == "post"
    assert committed["response"]["state"] == "needs_input"
    replay = store.begin_turn(
        "conversation:turn", "org:acme", "user:alice", "turn:client-1",
        expected_version=1, request={"text": "Send a Slack message"},
    )
    assert replay["duplicate"] is True
    assert replay["response"] == committed["response"]

    rows = store.repository._connection.execute(
        "SELECT count(*) AS count FROM concierge_turns"
    ).fetchone()
    assert rows["count"] == 1
    assert store.repository.count_outbox_events(
        "org:acme", "conversation-turn:conversation:turn:turn:client-1"
    ) == 1


def test_turn_key_reuse_and_parallel_base_version_fail_closed(tmp_path):
    store = _store(tmp_path)
    store.create("org:acme", "user:alice", "conversation:cas")
    store.begin_turn(
        "conversation:cas", "org:acme", "user:alice", "turn:a", 1,
        {"text": "first"},
    )
    with pytest.raises(RuntimeError, match="turn already in progress"):
        store.begin_turn(
            "conversation:cas", "org:acme", "user:alice", "turn:b", 1,
            {"text": "second"},
        )
    store.commit_turn(
        "conversation:cas", "org:acme", "user:alice", "turn:a", 1,
        {"locale": "en"}, {"state": "interpreting"},
    )

    with pytest.raises(RuntimeError, match="conversation version conflict"):
        store.begin_turn(
            "conversation:cas", "org:acme", "user:alice", "turn:b", 1,
            {"text": "second"},
        )
    current = store.get("conversation:cas", "org:acme", "user:alice")
    assert current["state_version"] == 2
    assert current["locale"] == "en"

    with pytest.raises(ValueError, match="different request"):
        store.begin_turn(
            "conversation:cas", "org:acme", "user:alice", "turn:a", 1,
            {"text": "changed"},
        )


def test_turn_commit_rolls_back_state_when_outbox_append_fails(tmp_path):
    store = _store(tmp_path)
    store.create("org:acme", "user:alice", "conversation:atomic")
    store.begin_turn(
        "conversation:atomic", "org:acme", "user:alice", "turn:atomic", 1,
        {"text": "send it"},
    )
    store.repository.append_outbox_event(
        "org:acme", "conversation", "conversation:atomic", "test.conflict",
        {"different": True},
        "conversation-turn:conversation:atomic:turn:atomic", 100,
    )

    with pytest.raises(ValueError, match="dedupe key was reused"):
        store.commit_turn(
            "conversation:atomic", "org:acme", "user:alice", "turn:atomic", 1,
            {"locale": "es"}, {"state": "interpreting"},
        )

    current = store.get("conversation:atomic", "org:acme", "user:alice")
    assert current["state_version"] == 1
    assert current.get("locale") is None
    turn = store.repository._connection.execute(
        "SELECT status, response_json FROM concierge_turns "
        "WHERE conversation_id = ? AND client_turn_id = ?",
        ("conversation:atomic", "turn:atomic"),
    ).fetchone()
    assert dict(turn) == {"status": "started", "response_json": None}


def test_turn_lookup_is_tenant_principal_scoped_and_survives_restart(tmp_path):
    database = str(tmp_path / "workflows.sqlite3")
    repository = WorkflowRepository(database)
    store = ConciergeConversationStore(repository, Clock(), ttl_seconds=180)
    store.create("org:acme", "user:alice", "conversation:restart")
    store.begin_turn(
        "conversation:restart", "org:acme", "user:alice", "turn:stable", 1,
        {"text": "hello"},
    )
    store.commit_turn(
        "conversation:restart", "org:acme", "user:alice", "turn:stable", 1,
        {"locale": "en"}, {"state": "ready"},
    )
    repository.close()

    restarted = ConciergeConversationStore(
        WorkflowRepository(database), Clock(), ttl_seconds=180
    )
    replay = restarted.begin_turn(
        "conversation:restart", "org:acme", "user:alice", "turn:stable", 1,
        {"text": "hello"},
    )
    assert replay["duplicate"] is True
    assert replay["response"] == {"state": "ready"}
    with pytest.raises(KeyError, match="conversation unavailable"):
        restarted.begin_turn(
            "conversation:restart", "org:other", "user:alice", "turn:stable", 1,
            {"text": "hello"},
        )
