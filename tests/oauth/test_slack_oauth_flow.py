import json
from urllib.parse import parse_qs, urlsplit

from libs.connectors.base import ProviderAuthority
from services.oauth.app import OAuthService
from services.oauth.repository import OAuthRepository


class SessionRepository:
    def resolve(self, session_id, now, touch=True):
        if session_id != "session-1":
            return None
        return {"principal_id": "user:alice", "tenant_id": "org:acme"}

    def csrf_matches(self, session_id, token):
        return session_id == "session-1" and token == "csrf-1"


class SlackConnector:
    def scope_catalog(self):
        return {
            "slack.channels.list": "channels:read",
            "slack.private_channels.list": "groups:read",
            "slack.private_conversation.read": "groups:history",
            "slack.private_thread.read": "groups:history",
            "slack.message.send": "chat:write",
        }

    def authorization_url(self, state, code_challenge, scopes):
        return "https://slack.test/oauth?state=%s&scope=%s" % (
            state, ",".join(scopes)
        )

    def exchange_code(self, code, verifier):
        assert code == "valid-code"
        return ProviderAuthority(
            access_token="xoxb-super-secret",
            refresh_token="xoxe-super-secret",
            expires_in=43200,
            granted_scopes=frozenset({"chat:write"}),
            token_type="bot",
            provider_metadata={
                "app_id": "A123",
                "team_id": "T123",
                "enterprise_id": "E123",
                "bot_user_id": "U-BOT",
            },
        )


class Crypto:
    def seal(self, plaintext, context, caller_identity):
        self.plaintext = plaintext
        return {"sealed": True, "encryption_context": context}


class Vault:
    def __init__(self):
        self.records = {}

    def store_managed_oauth(self, body, signer=None):
        credential_id = "cred:%s" % (len(self.records) + 1)
        self.records[credential_id] = body
        return 200, {"credential_id": credential_id}

    def delete_managed_oauth_credential(self, credential_id, owner):
        self.records.pop(credential_id, None)
        return 200


def _service(tmp_path):
    crypto = Crypto()
    vault = Vault()
    service = OAuthService(
        repository=OAuthRepository(str(tmp_path / "oauth.sqlite3")),
        session_repository=SessionRepository(),
        connector=object(),
        managed_oauth_crypto=crypto,
        vault_service=vault,
        clock=lambda: 100,
        slack_connector=SlackConnector(),
        slack_app_id="A123",
    )
    return service, crypto, vault


def test_connect_stores_workspace_but_returns_no_authority(tmp_path):
    service, crypto, vault = _service(tmp_path)
    status, started = service.initiate_slack(
        "session-1", "csrf-1", {
            "capabilities": ["slack.message.send", "slack.channels.list"],
            "intended_team_id": "T123",
        }
    )
    assert status == 200
    state = parse_qs(urlsplit(started["authorization_url"]).query)["state"][0]

    status, completed = service.complete_slack(
        "session-1", "valid-code", state
    )

    assert status == 200
    assert completed["team_id"] == "T123"
    assert completed["enabled_capabilities"] == ["slack.message.send"]
    assert "xox" not in json.dumps(completed)
    assert "xox" not in json.dumps(vault.records)
    sealed_document = json.loads(crypto.plaintext)
    assert sealed_document["access_token"] == "xoxb-super-secret"
    assert service.repository.list_installations(
        "org:acme", "user:alice", "slack"
    )[0]["enterprise_id"] == "E123"


def test_private_channel_capabilities_request_only_private_bot_scopes(tmp_path):
    service, _crypto, _vault = _service(tmp_path)

    status, started = service.initiate_slack(
        "session-1", "csrf-1", {
            "capabilities": [
                "slack.private_channels.list",
                "slack.private_conversation.read",
                "slack.private_thread.read",
            ],
        },
    )

    assert status == 200
    scopes = parse_qs(urlsplit(started["authorization_url"]).query)["scope"][0]
    assert set(scopes.split(",")) == {"groups:read", "groups:history"}


def test_state_is_one_use_and_wrong_session_stores_nothing(tmp_path):
    service, _crypto, vault = _service(tmp_path)
    _, started = service.initiate_slack(
        "session-1", "csrf-1", {"capabilities": ["slack.message.send"]}
    )
    state = parse_qs(urlsplit(started["authorization_url"]).query)["state"][0]

    assert service.complete_slack("wrong-session", "valid-code", state)[0] == 401
    assert service.complete_slack("session-1", "valid-code", state)[0] == 200
    assert service.complete_slack("session-1", "valid-code", state)[0] == 400
    assert len(vault.records) == 1
