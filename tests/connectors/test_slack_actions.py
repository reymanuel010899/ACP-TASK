import pytest
import requests

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


class InvalidJSONResponse(Response):
    def json(self):
        raise ValueError("invalid json")


class NetworkHTTP:
    def request(self, method, url, **kwargs):
        raise requests.ConnectionError("xoxb-secret must not escape")


def context():
    return {"access_token": "xoxb-secret", "connection_id": "conn:1", "team_id": "T1"}


def test_targeted_read_filters_messages_and_rejects_shared_channel():
    http = FakeHTTP([Response(payload={"ok": True, "messages": [{
        "ts": "1.1", "text": "hello", "user": "U1", "blocks": [{"secret": "drop"}],
    }]})])
    result = SlackActionExecutor(http=http).read(
        "slack.conversation.read", {"channel_id": "C1", "is_ext_shared": False}, context()
    )
    assert result == {"messages": [{"ts": "1.1", "text": "hello", "user": "U1", "thread_ts": None}], "next_cursor": None, "partial": False}
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
        "channels": [{"id": "C1", "name": "general", "is_private": False}],
        "next_cursor": None, "partial": False,
    }
    assert executor.read("slack.private_channels.list", {}, context()) == {
        "channels": [{"id": "G1", "name": "leadership", "is_private": True}],
        "next_cursor": None, "partial": False,
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

    membership = SlackActionExecutor(http=FakeHTTP([
        Response(payload={"ok": False, "error": "not_in_channel"}),
    ]))
    with pytest.raises(SlackAPIError) as denied:
        membership.execute(
            "slack.message.send", {"channel_id": "C1", "text": "x"}, context(),
        )
    assert denied.value.category == "membership"

    limited = SlackActionExecutor(http=FakeHTTP([Response(status=429, headers={"Retry-After": "7"})]))
    with pytest.raises(SlackRateLimitError) as rate:
        limited.read("slack.channels.list", {}, context())
    assert rate.value.retry_after == 7
    assert rate.value.connection_id == "conn:1"


def test_user_list_filters_non_humans_and_exposes_no_email():
    http = FakeHTTP([Response(payload={
        "ok": True,
        "members": [
            {"id": "U1", "name": "maria.one", "profile": {"display_name": "María", "real_name": "María Uno", "email": "secret@example.com", "image_48": "https://avatars.slack-edge.com/u1.png"}},
            {"id": "U2", "name": "maria.two", "profile": {"display_name": "María", "real_name": "María Dos"}},
            {"id": "B1", "name": "bot", "is_bot": True, "profile": {}},
            {"id": "U3", "deleted": True, "profile": {}},
        ],
        "response_metadata": {"next_cursor": "next"},
    })])

    result = SlackActionExecutor(http=http).read(
        "slack.users.list", {"cursor": "start", "limit": 500}, context()
    )

    assert [user["id"] for user in result["users"]] == ["U1", "U2"]
    assert result["users"][0]["display_name"] == result["users"][1]["display_name"]
    assert all("email" not in user for user in result["users"])
    assert result["next_cursor"] == "next"
    assert result["partial"] is True
    assert http.calls[0][2]["params"] == {"limit": 200, "cursor": "start"}


def test_bounded_history_and_permalink_preserve_source_binding():
    http = FakeHTTP([
        Response(payload={"ok": True, "messages": [], "response_metadata": {"next_cursor": "more"}}),
        Response(payload={"ok": True, "permalink": "https://acme.slack.com/archives/C1/p123"}),
    ])
    executor = SlackActionExecutor(http=http)
    page = executor.read("slack.conversation.read", {
        "channel_id": "C1", "oldest": "100.0", "latest": "200.0",
        "cursor": "cursor-1", "limit": 999,
    }, context())
    source = executor.read("slack.message.permalink", {
        "channel_id": "C1", "message_ts": "123.45",
    }, context())

    assert page == {"messages": [], "next_cursor": "more", "partial": True}
    assert http.calls[0][2]["params"] == {
        "channel": "C1", "limit": 100, "oldest": "100.0",
        "latest": "200.0", "cursor": "cursor-1",
    }
    assert source == {
        "channel_id": "C1", "message_ts": "123.45",
        "permalink": "https://acme.slack.com/archives/C1/p123",
    }


def test_public_resolver_rejects_archived_private_and_shared_channels():
    http = FakeHTTP([Response(payload={"ok": True, "channels": [
        {"id": "C1", "name": "good", "is_private": False},
        {"id": "C2", "name": "old", "is_archived": True},
        {"id": "C3", "name": "private", "is_private": True},
        {"id": "C4", "name": "connect", "is_ext_shared": True},
    ]})])
    result = SlackActionExecutor(http=http).read("slack.channels.list", {}, context())
    assert [channel["id"] for channel in result["channels"]] == ["C1"]


def test_direct_message_opens_selected_user_then_posts_exactly_once():
    http = FakeHTTP([
        Response(payload={"ok": True, "channel": {"id": "D1"}}),
        Response(payload={"ok": True, "channel": "D1", "ts": "123.45"}),
    ])
    receipt = SlackActionExecutor(http=http).execute(
        "slack.direct_message.send", {"user_id": "U2", "text": "Hola"}, context()
    )
    assert [call[1].rsplit("/", 1)[-1] for call in http.calls] == [
        "conversations.open", "chat.postMessage"
    ]
    assert http.calls[0][2]["json"] == {"users": "U2"}
    assert http.calls[1][2]["json"]["text"] == "Hola"
    assert receipt["user_id"] == "U2"
    assert receipt["channel_id"] == "D1"


def test_dm_missing_scope_stops_before_post_and_public_send_remains_independent():
    missing = FakeHTTP([Response(payload={
        "ok": False, "error": "missing_scope", "needed": "im:write"
    })])
    with pytest.raises(SlackAPIError) as caught:
        SlackActionExecutor(http=missing).execute(
            "slack.direct_message.send", {"user_id": "U2", "text": "Hola"}, context()
        )
    assert caught.value.category == "scope"
    assert len(missing.calls) == 1

    public = FakeHTTP([Response(payload={"ok": True, "ts": "1.0"})])
    assert SlackActionExecutor(http=public).execute(
        "slack.message.send", {"channel_id": "C1", "text": "Hola"}, context()
    )["message_ts"] == "1.0"


def test_invalid_json_and_network_failures_are_typed_without_token_leakage():
    with pytest.raises(SlackAPIError) as invalid:
        SlackActionExecutor(http=FakeHTTP([InvalidJSONResponse()])).read(
            "slack.users.list", {}, context()
        )
    assert invalid.value.code == "invalid_json"
    with pytest.raises(Exception) as network:
        SlackActionExecutor(http=NetworkHTTP()).read("slack.users.list", {}, context())
    assert network.value.__class__.__name__ == "ProviderNetworkError"
    assert "xoxb" not in str(network.value)


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


def test_removing_a_reaction_calls_slack_once_with_the_exact_target():
    http = FakeHTTP([Response(payload={"ok": True})])
    executor = SlackActionExecutor(http=http)

    receipt = executor.execute("slack.reaction.remove", {
        "channel_id": "C1", "message_ts": "10.1", "reaction": "thumbsup",
    }, context())

    method, url, kwargs = http.calls[0]
    assert url.endswith("/reactions.remove")
    assert kwargs["json"] == {
        "channel": "C1", "timestamp": "10.1", "name": "thumbsup",
    }
    assert receipt["capability_id"] == "slack.reaction.remove"
    assert receipt["provider_id"] == "C1:10.1:thumbsup"
    assert receipt["team_id"] == "T1"


@pytest.mark.parametrize("code", ["no_reaction", "message_not_found"])
def test_removing_an_absent_reaction_is_the_state_the_caller_asked_for(code):
    http = FakeHTTP([Response(payload={"ok": False, "error": code})])
    executor = SlackActionExecutor(http=http)

    receipt = executor.execute("slack.reaction.remove", {
        "channel_id": "C1", "message_ts": "10.1", "reaction": "thumbsup",
    }, context())

    assert receipt["reaction"] == "thumbsup"
    assert receipt["message_ts"] == "10.1"


def test_a_denied_reaction_removal_still_fails():
    http = FakeHTTP([Response(payload={"ok": False, "error": "missing_scope"})])
    executor = SlackActionExecutor(http=http)

    with pytest.raises(SlackAPIError) as failure:
        executor.execute("slack.reaction.remove", {
            "channel_id": "C1", "message_ts": "10.1", "reaction": "thumbsup",
        }, context())

    assert failure.value.code == "missing_scope"
    assert failure.value.category == "scope"


def test_a_direct_message_declares_both_scopes_its_executor_uses():
    from libs.integrations.catalog import slack_definitions

    definition = next(item for item in slack_definitions()
                      if item.capability_id == "slack.direct_message.send")

    # conversations.open needs im:write and chat.postMessage needs chat:write;
    # declaring one would let a workspace pass the check and fail at Slack.
    assert definition.required_scopes == frozenset({"im:write", "chat:write"})
