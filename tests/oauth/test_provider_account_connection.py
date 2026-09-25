import json

from libs.connectors.base import ProviderHTTPError, StaticCredentialConnector
from services.oauth.app import OAuthService, _default_account_connectors
from services.oauth.repository import OAuthRepository


ACCOUNT_ID = "AC0000000000000000000000000000001"
SENDER_A = "+18095550100"
SENDER_B = "+18095550200"


class SessionRepository:
    def resolve(self, session_id, now, touch=True):
        if session_id != "session-1":
            return None
        return {"principal_id": "user:alice", "tenant_id": "org:acme"}

    def csrf_matches(self, session_id, token):
        return (session_id, token) == ("session-1", "csrf-1")


class AccountConnector(StaticCredentialConnector):
    provider = "twilio"

    def __init__(self):
        self.senders = [
            {"sender_id": SENDER_A, "family": "sms", "countries": ["ES"]},
            {"sender_id": SENDER_B, "family": "sms", "countries": ["DO"]},
        ]
        self.status = "verified"
        self.verifications = []

    def verify_account(self, account_id, auth_token):
        self.verifications.append((account_id, auth_token))
        return {
            "provider": "twilio",
            "account_id": account_id,
            "status": self.status,
            "families": ["sms:send"],
            "senders": [dict(sender) for sender in self.senders],
        }

    def scope_catalog(self):
        return {"twilio.sms.send": frozenset({"twilio:sms:send"})}


class FailingConnector(AccountConnector):
    def verify_account(self, account_id, auth_token):
        raise ProviderHTTPError("twilio", 401, "account verification")


class Crypto:
    def __init__(self):
        self.contexts = []

    def seal(self, plaintext, context, caller_identity):
        self.plaintext = plaintext
        self.contexts.append(context)
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


def _service(tmp_path, connector=None):
    connector = connector or AccountConnector()
    crypto = Crypto()
    service = OAuthService(
        repository=OAuthRepository(str(tmp_path / "oauth.sqlite3")),
        session_repository=SessionRepository(),
        connector=None,
        managed_oauth_crypto=crypto,
        vault_service=Vault(),
        clock=lambda: 1_700_000_000,
        account_connectors={"twilio": connector},
    )
    return service, connector, crypto


def _connect(service):
    return service.connect_provider_account("session-1", "csrf-1", {
        "provider": "twilio",
        "account_id": ACCOUNT_ID,
        "auth_token": "static-auth-token",
    })


def test_an_account_credential_connects_without_any_redirect(tmp_path):
    service, connector, crypto = _service(tmp_path)

    status, body = _connect(service)

    assert status == 200
    assert body["provider_account_id"] == ACCOUNT_ID
    assert connector.verifications == [(ACCOUNT_ID, "static-auth-token")]
    # Authority came from the account, not from a consent screen.
    assert body["effective_scopes"] == [
        "twilio:geo:DO", "twilio:geo:ES",
        "twilio:sender:%s" % SENDER_A, "twilio:sender:%s" % SENDER_B,
        "twilio:sms:send",
    ]
    assert body["enabled_capabilities"] == ["twilio.sms.send"]
    assert crypto.contexts[0]["provider_account_id"] == ACCOUNT_ID


def test_the_sealed_document_carries_both_halves_of_the_credential(tmp_path):
    service, _connector, crypto = _service(tmp_path)

    _connect(service)
    document = json.loads(crypto.plaintext)

    assert document["account_id"] == ACCOUNT_ID
    assert document["auth_token"] == "static-auth-token"
    assert document["token_type"] == "account"
    # No refresh token, because there is nothing to refresh.
    assert "refresh_token" not in document


def test_the_first_sealing_of_a_static_secret_is_credential_version_one(
    tmp_path,
):
    service, _connector, _crypto = _service(tmp_path)

    _status, body = _connect(service)
    installation = service.repository.get_installation(
        body["connection_id"], "org:acme"
    )

    assert installation["credential_version"] == 1


def test_an_unverified_account_never_gains_sealed_authority(tmp_path):
    service, connector, _crypto = _service(tmp_path)
    connector.status = "unavailable"

    status, body = _connect(service)

    assert status == 409
    assert body["account_status"] == "unavailable"
    assert service.vault_service.records == {}


def test_twilio_account_without_numbers_gets_an_actionable_error(tmp_path):
    service, connector, _crypto = _service(tmp_path)
    connector.senders = []
    connector.verify_account = lambda account_id, _token: {
        "provider": "twilio",
        "account_id": account_id,
        "status": "verified",
        "families": [],
        "senders": [],
    }

    status, body = _connect(service)

    assert status == 409
    assert "no SMS- or Voice-capable incoming phone numbers" in body["error"]
    assert service.vault_service.records == {}


def test_an_unreachable_provider_is_a_failure_not_an_empty_connection(
    tmp_path,
):
    service, _connector, _crypto = _service(tmp_path, FailingConnector())

    status, body = _connect(service)

    assert status == 502
    assert body["error"] == "provider account could not be verified"


def test_a_provider_with_no_configured_connector_is_refused(tmp_path):
    service, _connector, _crypto = _service(tmp_path)

    status, body = service.connect_provider_account("session-1", "csrf-1", {
        "provider": "unregistered", "account_id": "X", "auth_token": "y",
    })

    assert status == 503
    assert body["error"] == "provider is not configured"


def test_the_real_oauth_composition_installs_twilio(monkeypatch):
    monkeypatch.setenv("TWILIO_PUBLIC_CALLBACK_BASE", "https://callbacks.test")

    connectors = _default_account_connectors()

    assert set(connectors) == {"twilio"}
    assert connectors["twilio"].provider == "twilio"
    assert connectors["twilio"].expected_callback_base == "https://callbacks.test"


def test_reverification_narrows_authority_without_touching_the_credential(
    tmp_path,
):
    service, connector, _crypto = _service(tmp_path)
    _status, connected = _connect(service)
    before = service.repository.get_installation(
        connected["connection_id"], "org:acme"
    )

    # One sender is disabled at the provider. Nothing else changes.
    connector.senders[0]["enabled"] = False
    status, body = service.apply_verified_account_state(
        "org:acme", connected["connection_id"],
        connector.verify_account(ACCOUNT_ID, "static-auth-token"),
    )

    assert status == 200
    assert body["effective_scopes"] == [
        "twilio:geo:DO", "twilio:sender:%s" % SENDER_B, "twilio:sms:send",
    ]
    # The secret did not change, so the version that fences it must not move:
    # bumping it would fail every queued effect on the whole connection.
    assert body["credential_version"] == before["credential_version"]
    assert body["enabled_capabilities"] == ["twilio.sms.send"]


def test_an_account_that_stops_verifying_loses_all_derived_authority(tmp_path):
    service, connector, _crypto = _service(tmp_path)
    _status, connected = _connect(service)
    connector.status = "suspended"

    _status, body = service.apply_verified_account_state(
        "org:acme", connected["connection_id"],
        connector.verify_account(ACCOUNT_ID, "static-auth-token"),
    )

    assert body["effective_scopes"] == []
    assert body["enabled_capabilities"] == []
    assert body["account_status"] == "suspended"


def test_reverification_refuses_state_from_a_different_provider(tmp_path):
    service, connector, _crypto = _service(tmp_path)
    _status, connected = _connect(service)
    state = connector.verify_account(ACCOUNT_ID, "static-auth-token")
    state["provider"] = "elsewhere"

    status, body = service.apply_verified_account_state(
        "org:acme", connected["connection_id"], state,
    )

    assert status == 409
    assert body["error"] == "provider account identity does not match"


def test_connecting_an_account_still_requires_a_session_and_csrf_token(
    tmp_path,
):
    service, _connector, _crypto = _service(tmp_path)
    body = {
        "provider": "twilio",
        "account_id": ACCOUNT_ID,
        "auth_token": "static-auth-token",
    }

    assert service.connect_provider_account("session-9", "csrf-1", body)[0] == 401
    assert service.connect_provider_account("session-1", "wrong", body)[0] == 403
