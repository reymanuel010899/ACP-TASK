import json
from urllib.parse import parse_qs, urlsplit

from libs.connectors.base import ProviderAuthority
from services.oauth.app import OAuthService
from services.oauth.repository import OAuthRepository


class SessionRepository:
    def resolve(self, session_id, now, touch=True):
        principals = {"session-1": "user:alice", "session-2": "user:bob"}
        if session_id not in principals:
            return None
        return {"principal_id": principals[session_id], "tenant_id": "org:acme"}

    def csrf_matches(self, session_id, token):
        return (session_id, token) in {
            ("session-1", "csrf-1"), ("session-2", "csrf-2")
        }


class SlackConnector:
    def scope_catalog(self):
        # Mirrors the real contract: a capability declares every scope its
        # executor needs, so the DM carries both of its.
        return {
            "slack.channels.list": frozenset({"channels:read"}),
            "slack.private_channels.list": frozenset({"groups:read"}),
            "slack.private_conversation.read": frozenset({"groups:history"}),
            "slack.private_thread.read": frozenset({"groups:history"}),
            "slack.message.send": frozenset({"chat:write"}),
            "slack.users.list": frozenset({"users:read"}),
            "slack.message.permalink": frozenset({"channels:history"}),
            "slack.direct_message.send": frozenset({"im:write", "chat:write"}),
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
        self.sequence = 0

    def store_managed_oauth(self, body, signer=None):
        self.sequence += 1
        credential_id = "cred:%s" % self.sequence
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


def test_people_and_dm_upgrade_requests_only_optional_bot_scopes(tmp_path):
    service, _crypto, _vault = _service(tmp_path)
    status, started = service.initiate_slack(
        "session-1", "csrf-1", {"capabilities": [
            "slack.users.list", "slack.direct_message.send"
        ]},
    )
    assert status == 200
    scopes = parse_qs(urlsplit(started["authorization_url"]).query)["scope"][0]
    # chat:write travels with the DM: its executor posts after opening.
    assert set(scopes.split(",")) == {"users:read", "im:write", "chat:write"}


def test_tenant_member_can_see_owner_installation_but_cannot_mutate_it(tmp_path):
    service, _crypto, _vault = _service(tmp_path)
    connection = service.repository.upsert_installation(
        tenant_id="org:acme", principal_id="user:alice", provider="slack",
        app_id="A123", team_id="T123", credential_id="cred:1",
        granted_scopes=["channels:read"],
        enabled_capabilities=["slack.channels.list"], now_ts=1,
    )

    status, body = service.slack_status("session-2")
    assert status == 200
    assert body["connections"][0]["connection_id"] == connection["connection_id"]
    assert body["connections"][0]["owner"] is False
    assert service.initiate_slack("session-2", "csrf-2", {
        "capabilities": ["slack.users.list"],
        "target_connection_id": connection["connection_id"],
        "intended_team_id": "T123",
    })[0] == 404
    assert service.disconnect_slack(
        "session-2", "csrf-2", connection["connection_id"]
    )[0] == 404


def test_fresh_consent_repairs_orphaned_workspace_for_same_tenant(tmp_path):
    service, _crypto, vault = _service(tmp_path)
    _, started = service.initiate_slack(
        "session-1", "csrf-1", {"capabilities": ["slack.message.send"]}
    )
    first_state = parse_qs(
        urlsplit(started["authorization_url"]).query
    )["state"][0]
    status, first = service.complete_slack(
        "session-1", "valid-code", first_state
    )
    assert status == 200
    original = service.repository.get_installation(
        first["connection_id"], "org:acme"
    )
    vault.records.pop(original["credential_id"])

    _, restarted = service.initiate_slack(
        "session-2", "csrf-2", {"capabilities": ["slack.message.send"]}
    )
    second_state = parse_qs(
        urlsplit(restarted["authorization_url"]).query
    )["state"][0]
    status, repaired = service.complete_slack(
        "session-2", "valid-code", second_state
    )

    assert status == 200
    assert repaired["connection_id"] == first["connection_id"]
    current = service.repository.get_installation(
        repaired["connection_id"], "org:acme"
    )
    assert current["principal_id"] == "user:bob"
    assert current["credential_id"] == "cred:2"
    assert "cred:2" in vault.records


def test_same_tenant_reauthorization_retires_replaced_credential(tmp_path):
    service, _crypto, vault = _service(tmp_path)
    connection_ids = []
    for session_id, csrf_token in (
        ("session-1", "csrf-1"), ("session-2", "csrf-2")
    ):
        _, started = service.initiate_slack(
            session_id, csrf_token,
            {"capabilities": ["slack.message.send"]},
        )
        state = parse_qs(
            urlsplit(started["authorization_url"]).query
        )["state"][0]
        status, completed = service.complete_slack(
            session_id, "valid-code", state
        )
        assert status == 200
        connection_ids.append(completed["connection_id"])

    assert connection_ids[0] == connection_ids[1]
    assert set(vault.records) == {"cred:2"}


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


def test_configured_local_tenant_fallback_survives_principal_rotation(monkeypatch):
    from services.oauth.app import _configured_tenant_resolver

    monkeypatch.setenv("TESSERA_PRINCIPAL_TENANTS_JSON", "{}")
    monkeypatch.setenv("TESSERA_LOCAL_TENANT_ID", "org:local")

    assert _configured_tenant_resolver()("new-principal") == "org:local"
