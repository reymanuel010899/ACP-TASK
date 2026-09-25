"""A consent round that asks only for personal scopes.

Slack answers such a round with an ``authed_user`` block and no bot token.
That is correct, and the service used to reject it: it demanded a bot
authority unconditionally, so nobody could ever grant search access as
themselves. The round also must not touch the installation — agreeing to
search as yourself is not agreeing to reinstall the app.
"""

import pytest

from libs.connectors.base import ProviderAuthority, ProviderHTTPError
from libs.connectors.slack import SlackCredentialConnector
from services.oauth.app import OAuthService
from services.oauth.repository import OAuthRepository


class SessionRepository:
    def resolve(self, session_id, now, touch=True):
        if session_id != "session-1":
            return None
        return {"principal_id": "user:alice", "tenant_id": "org:acme"}

    def csrf_matches(self, session_id, token):
        return (session_id, token) == ("session-1", "csrf-1")


class Connector:
    """Returns whatever Slack would for the round that was asked for."""

    def __init__(self):
        self.require_bot_calls = []

    def scope_catalog(self):
        return {
            "slack.message.send": frozenset({"chat:write"}),
            "slack.channels.list": frozenset({"channels:read"}),
            "slack.search.messages": frozenset({"search:read"}),
        }

    def authorization_url(self, state, code_challenge, scopes,
                          user_scopes=None):
        return "https://slack.test/oauth?state=%s" % state

    def exchange_code_with_user(self, code, require_bot=True):
        self.require_bot_calls.append(require_bot)
        user = {
            "slack_subject_id": "U-ALICE",
            "access_token": "xoxp-personal",
            "refresh_token": "xoxe-personal",
            "expires_in": 43200,
            "granted_scopes": frozenset({"search:read"}),
            "token_type": "user",
        }
        if not require_bot:
            return None, user
        return ProviderAuthority(
            access_token="xoxb-secret",
            refresh_token="xoxe-secret",
            expires_in=43200,
            granted_scopes=frozenset({"chat:write", "channels:read"}),
            token_type="bot",
            provider_metadata={
                "app_id": "A123", "team_id": "T123",
                "enterprise_id": None, "bot_user_id": "U-BOT",
            },
        ), None


class Crypto:
    def seal(self, plaintext, context, caller_identity):
        return {"sealed": True, "encryption_context": context}


class Vault:
    def __init__(self):
        self.records = {}
        self.deleted = []
        self.sequence = 0

    def store_managed_oauth(self, body, signer=None):
        self.sequence += 1
        credential_id = "cred:%s" % self.sequence
        self.records[credential_id] = body
        return 200, {"credential_id": credential_id}

    def delete_managed_oauth_credential(self, credential_id, owner):
        self.deleted.append(credential_id)
        self.records.pop(credential_id, None)
        return 200

    def begin_managed_oauth_revocation(self, credential_id, owner):
        # Enough of the revocation contract for the routing test below; the
        # disconnect path itself is covered by the flow tests.
        return 409, {}


def _service(tmp_path):
    connector = Connector()
    vault = Vault()
    service = OAuthService(
        repository=OAuthRepository(str(tmp_path / "oauth.sqlite3")),
        session_repository=SessionRepository(),
        connector=object(),
        managed_oauth_crypto=Crypto(),
        vault_service=vault,
        clock=lambda: 100,
        slack_connector=connector,
        slack_app_id="A123",
    )
    return service, connector, vault


def _install(service):
    """Complete an ordinary workspace install and return its connection id."""
    status, started = service.initiate_slack("session-1", "csrf-1", {
        "capabilities": ["slack.message.send", "slack.channels.list"],
        "intended_team_id": "T123",
    })
    assert status == 200
    state = started["authorization_url"].split("state=")[1]
    status, body = service.complete_slack("session-1", "valid-code", state)
    assert status == 200, body
    return body["connection_id"]


def test_a_personal_round_completes_without_a_bot_token(tmp_path):
    service, connector, vault = _service(tmp_path)
    connection_id = _install(service)
    installed_credential = service.repository.get_installation(
        connection_id, "org:acme"
    )["credential_id"]

    status, started = service.initiate_slack("session-1", "csrf-1", {
        "capabilities": ["slack.search.messages"],
        "target_connection_id": connection_id,
    })
    assert status == 200
    state = started["authorization_url"].split("state=")[1]
    status, body = service.complete_slack("session-1", "valid-code", state)

    assert status == 200, body
    assert body["result"] == "connected"
    # The connector was told this round carries no bot authority.
    assert connector.require_bot_calls == [True, False]


def test_a_personal_round_leaves_the_installation_untouched(tmp_path):
    service, connector, vault = _service(tmp_path)
    connection_id = _install(service)
    before = service.repository.get_installation(connection_id, "org:acme")

    status, started = service.initiate_slack("session-1", "csrf-1", {
        "capabilities": ["slack.search.messages"],
        "target_connection_id": connection_id,
    })
    state = started["authorization_url"].split("state=")[1]
    service.complete_slack("session-1", "valid-code", state)

    after = service.repository.get_installation(connection_id, "org:acme")
    # Consenting to search as yourself must not replace or retire the
    # workspace's credential.
    assert after["credential_id"] == before["credential_id"]
    assert vault.deleted == []


def test_personal_consent_is_stored_as_its_own_credential(tmp_path):
    service, connector, vault = _service(tmp_path)
    connection_id = _install(service)
    status, started = service.initiate_slack("session-1", "csrf-1", {
        "capabilities": ["slack.search.messages"],
        "target_connection_id": connection_id,
    })
    state = started["authorization_url"].split("state=")[1]
    service.complete_slack("session-1", "valid-code", state)

    personal = [
        body for body in vault.records.values()
        if body["provider"] == "slack-user"
    ]
    assert len(personal) == 1
    assert personal[0]["granted_scopes"] == ["search:read"]
    # A personal grant is consent, not enablement.
    profiles = service.repository.list_personal_authority(
        "org:acme", connection_id, "user:alice",
    )
    assert profiles and profiles[0]["enabled"] is False


def test_a_personal_round_without_an_installation_is_refused(tmp_path):
    service, connector, vault = _service(tmp_path)
    status, started = service.initiate_slack("session-1", "csrf-1", {
        "capabilities": ["slack.search.messages"],
        "intended_team_id": "T123",
    })
    assert status == 200
    state = started["authorization_url"].split("state=")[1]
    status, body = service.complete_slack("session-1", "valid-code", state)

    assert status == 409
    assert body["error"] == "personal consent target changed"


def test_a_bot_round_still_requires_a_bot_token():
    """The relaxation must not weaken the ordinary install path."""
    connector = SlackCredentialConnector(
        "id", "secret", "https://localhost/callback",
        http=_StubHTTP({"ok": True, "authed_user": {
            "id": "U1", "access_token": "xoxp-x", "scope": "search:read",
        }}),
    )
    with pytest.raises(ProviderHTTPError):
        connector.exchange_code_with_user("code", require_bot=True)


def test_a_personal_round_still_requires_a_personal_token():
    """An empty payload is a failure, not a silent no-op grant."""
    connector = SlackCredentialConnector(
        "id", "secret", "https://localhost/callback",
        http=_StubHTTP({"ok": True}),
    )
    with pytest.raises(ProviderHTTPError):
        connector.exchange_code_with_user("code", require_bot=False)


class _StubHTTP:
    def __init__(self, payload):
        self._payload = payload

    def request(self, *args, **kwargs):
        return self

    def post(self, *args, **kwargs):
        return self

    status_code = 200

    def json(self):
        return self._payload


def test_a_disconnect_path_decodes_the_identifier_the_browser_sent(tmp_path):
    """A connection id contains a colon, and every caller encodes it.

    Reading the raw path segment looked up "conn%3A..." and answered 404 on a
    connection that plainly exists, which made disconnecting impossible from
    the browser and left people reconnecting instead.
    """
    from urllib.parse import quote, unquote, urlsplit

    service, connector, vault = _service(tmp_path)
    connection_id = _install(service)
    encoded = quote(connection_id, safe="")
    assert "%3A" in encoded

    # Exactly what the handler does with the request line.
    decoded = unquote(
        urlsplit("/oauth/slack/%s" % encoded).path[len("/oauth/slack/"):]
    )
    assert decoded == connection_id

    status, _ = service.disconnect_slack("session-1", "csrf-1", decoded)
    assert status != 404
    # The undecoded form is what used to be passed, and it names no
    # connection the repository knows.
    status, body = service.disconnect_slack("session-1", "csrf-1", encoded)
    assert status == 404
    assert body["error"] == "Slack connection not found"
