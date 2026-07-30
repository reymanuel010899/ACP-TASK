import pytest

from libs.connectors.slack import SlackAPIError, SlackActionExecutor, SlackRateLimitError
from services.action_broker.rate_limits import SlackRatePolicy


class Response:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def context():
    return {"access_token": "xoxb-secret", "connection_id": "conn:1", "team_id": "T1"}


def test_targeted_read_filters_messages_and_rejects_shared_channel():
    http = FakeHTTP([Response(payload={"ok": True, "messages": [{
        "ts": "1.1", "text": "hello", "user": "U1", "blocks": [{"secret": "drop"}],
    }]})])
    result = SlackActionExecutor(http=http).read(
        "slack.conversation.read", {"channel_id": "C1", "is_ext_shared": False}, context()
    )
    assert result == {"messages": [{"ts": "1.1", "text": "hello", "user": "U1", "thread_ts": None}]}
    with pytest.raises(ValueError, match="Slack Connect"):
        SlackActionExecutor(http=http).read(
            "slack.conversation.read", {"channel_id": "C2", "is_ext_shared": True}, context()
        )


def test_public_and_private_channel_lists_request_only_their_authorized_type():
    http = FakeHTTP([
        Response(payload={"ok": True, "channels": [
            {"id": "C1", "name": "general", "is_private": False},
        ]}),
        Response(payload={"ok": True, "channels": [
            {"id": "G1", "name": "leadership", "is_private": True},
        ]}),
    ])
    executor = SlackActionExecutor(http=http)

    assert executor.read("slack.channels.list", {}, context()) == {
        "channels": [{"id": "C1", "name": "general", "is_private": False}]
    }
    assert executor.read("slack.private_channels.list", {}, context()) == {
        "channels": [{"id": "G1", "name": "leadership", "is_private": True}]
    }
    assert http.calls[0][2]["params"]["types"] == "public_channel"
    assert http.calls[1][2]["params"]["types"] == "private_channel"


def test_private_conversation_and_thread_reads_use_the_filtered_read_paths():
    http = FakeHTTP([
        Response(payload={"ok": True, "messages": [
            {"ts": "1.1", "text": "private", "user": "U1"},
        ]}),
        Response(payload={"ok": True, "messages": [
            {"ts": "1.2", "text": "reply", "user": "U2", "thread_ts": "1.1"},
        ]}),
    ])
    executor = SlackActionExecutor(http=http)

    conversation = executor.read(
        "slack.private_conversation.read",
        {"channel_id": "G1", "is_ext_shared": False},
        context(),
    )
    thread = executor.read(
        "slack.private_thread.read",
        {"channel_id": "G1", "thread_ts": "1.1", "is_ext_shared": False},
        context(),
    )

    assert conversation["messages"][0]["text"] == "private"
    assert thread["messages"][0]["thread_ts"] == "1.1"


def test_message_write_disables_unfurls_and_returns_minimal_receipt():
    http = FakeHTTP([Response(payload={"ok": True, "channel": "C1", "ts": "123.45", "message": {"text": "secret-copy"}})])
    receipt = SlackActionExecutor(http=http).execute(
        "slack.message.send", {"channel_id": "C1", "text": "Hello"}, context()
    )
    sent = http.calls[0][2]["json"]
    assert sent == {"channel": "C1", "text": "Hello", "unfurl_links": False, "unfurl_media": False}
    assert receipt == {
        "provider": "slack", "capability_id": "slack.message.send",
        "provider_id": "123.45", "team_id": "T1", "channel_id": "C1",
        "message_ts": "123.45",
    }
    assert "text" not in receipt


def test_ok_false_and_rate_limit_are_typed_without_token_leakage():
    missing = SlackActionExecutor(http=FakeHTTP([Response(payload={"ok": False, "error": "missing_scope", "needed": "files:write"})]))
    with pytest.raises(SlackAPIError) as caught:
        missing.execute("slack.message.send", {"channel_id": "C1", "text": "x"}, context())
    assert "xoxb" not in str(caught.value)

    limited = SlackActionExecutor(http=FakeHTTP([Response(status=429, headers={"Retry-After": "7"})]))
    with pytest.raises(SlackRateLimitError) as rate:
        limited.read("slack.channels.list", {}, context())
    assert rate.value.retry_after == 7
    assert rate.value.connection_id == "conn:1"


def test_file_upload_rejects_untrusted_upload_host_before_bytes_leave():
    http = FakeHTTP([Response(payload={
        "ok": True,
        "upload_url": "http://169.254.169.254/latest/meta-data",
        "file_id": "F1",
    })])
    executor = SlackActionExecutor(http=http, host_resolver=lambda host: ["169.254.169.254"])
    with pytest.raises(ValueError, match="upload host"):
        executor.execute("slack.file.upload", {
            "channel_id": "C1", "filename": "brief.txt", "content": b"hello",
            "title": "Brief",
        }, context())
    assert len(http.calls) == 1


def test_rate_limit_is_scoped_to_connection_and_method():
    clock = lambda: 100
    policy = SlackRatePolicy(clock=clock)
    policy.block("conn:a", "conversations.history", 10)

    with pytest.raises(SlackRateLimitError):
        policy.check("conn:a", "conversations.history")
    policy.check("conn:b", "conversations.history")
    policy.check("conn:a", "chat.postMessage")
