from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from libs.config import ConfigurationError, get_slack_oauth_config
from libs.connectors.base import ProviderHTTPError, ProviderNetworkError
from libs.connectors.slack import SlackCredentialConnector


class Response:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def connector(http):
    return SlackCredentialConnector(
        "client-id", "client-secret", "https://app.test/oauth/slack/callback",
        http=http,
    )


def test_slack_config_fails_closed():
    config = get_slack_oauth_config({
        "SLACK_OAUTH_CLIENT_ID": "id",
        "SLACK_OAUTH_CLIENT_SECRET": "secret",
        "SLACK_OAUTH_REDIRECT_URI": "https://app.test/callback",
        "SLACK_OAUTH_APP_ID": "A123",
    })
    assert config.app_id == "A123"
    with pytest.raises(ConfigurationError):
        get_slack_oauth_config({})


def test_authorization_is_bot_only_and_state_bound_without_pkce():
    url = connector(FakeHTTP([])).authorization_url(
        "state-1", None, ["chat:write", "channels:read"]
    )
    query = parse_qs(urlsplit(url).query)
    assert query["state"] == ["state-1"]
    assert set(query["scope"][0].split(",")) == {"chat:write", "channels:read"}
    assert "user_scope" not in query
    assert "code_challenge" not in query


def test_scope_catalog_keeps_private_channel_authority_explicit():
    catalog = connector(FakeHTTP([])).scope_catalog()

    assert catalog["slack.channels.list"] == "channels:read"
    assert catalog["slack.conversation.read"] == "channels:history"
    assert catalog["slack.private_channels.list"] == "groups:read"
    assert catalog["slack.private_conversation.read"] == "groups:history"
    assert catalog["slack.private_thread.read"] == "groups:history"
    assert catalog["slack.users.list"] == "users:read"
    assert catalog["slack.message.permalink"] == "channels:history"
    assert catalog["slack.direct_message.send"] == "im:write"


def test_exchange_requires_bot_authority_and_keeps_workspace_metadata():
    http = FakeHTTP([Response(payload={
        "ok": True,
        "app_id": "A123",
        "access_token": "xoxb-access",
        "refresh_token": "xoxe-refresh",
        "expires_in": 43200,
        "scope": "chat:write,channels:read",
        "token_type": "bot",
        "bot_user_id": "U-BOT",
        "team": {"id": "T123", "name": "Acme"},
        "enterprise": {"id": "E123", "name": "Acme Grid"},
    })])
    authority = connector(http).exchange_code("code", None)
    assert authority.refresh_token == "xoxe-refresh"
    assert authority.granted_scopes == frozenset({"chat:write", "channels:read"})
    assert authority.provider_metadata["team_id"] == "T123"
    assert authority.provider_metadata["enterprise_id"] == "E123"
    assert authority.provider_metadata["bot_user_id"] == "U-BOT"


def test_exchange_accepts_rotating_bot_access_token():
    http = FakeHTTP([Response(payload={
        "ok": True,
        "access_token": "xoxe.xoxb-rotating-access",
        "refresh_token": "xoxe-refresh",
        "expires_in": 43200,
        "scope": "chat:write",
        "token_type": "bot",
    })])

    authority = connector(http).exchange_code("code", None)

    assert authority.access_token == "xoxe.xoxb-rotating-access"


@pytest.mark.parametrize("payload", [
    {"ok": True, "authed_user": {"access_token": "xoxp-user"}},
    {
        "ok": True,
        "access_token": "xoxe.xoxp-rotating-user",
        "refresh_token": "xoxe-refresh",
        "expires_in": 43200,
        "token_type": "user",
    },
    {"ok": False, "error": "invalid_code"},
])
def test_exchange_rejects_user_only_or_slack_logical_error(payload):
    with pytest.raises(ProviderHTTPError):
        connector(FakeHTTP([Response(payload=payload)])).exchange_code("code", None)


def test_refresh_uses_no_scope_override_and_network_errors_are_typed():
    http = FakeHTTP([
        Response(payload={
            "ok": True,
            "access_token": "xoxb-next",
            "refresh_token": "xoxe-next",
            "expires_in": 43200,
            "scope": "chat:write",
            "token_type": "bot",
        }),
        requests.ConnectionError("offline"),
    ])
    slack = connector(http)
    refreshed = slack.refresh("xoxe-current")
    assert refreshed.refresh_token == "xoxe-next"
    assert "scope" not in http.calls[0][2]["data"]
    with pytest.raises(ProviderNetworkError):
        slack.refresh("xoxe-next")
