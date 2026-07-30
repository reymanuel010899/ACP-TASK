"""Integration tests for session-bound, one-use Google OAuth (U3)."""

import json
import os
from urllib.parse import parse_qs, urlsplit

import pytest

from libs.aws_kms import GeneratedDataKey, KMSAccessDenied
from libs.connectors.base import ProviderAuthority, ProviderNetworkError
from services.oauth.app import OAuthService
from services.oauth.repository import OAuthRepository
from services.session.repository import SessionRepository
from vault.app import VaultService
from vault.managed_oauth_crypto import ManagedOAuthCrypto


NOW = 1_700_000_000
INGESTION = "service:oauth-ingestion"
BROKER = "service:credential-broker"


class Clock(object):
    def __init__(self, value=NOW):
        self.value = value

    def __call__(self):
        return self.value


class FakeConnector(object):
    scopes = {
        "calendar.create": "scope.calendar",
        "calendar.read": "scope.calendar.read",
        "gmail.send": "scope.gmail.send",
    }

    def __init__(self):
        self.exchanges = []
        self.revocations = []
        self.authorization_calls = []
        self.exchange_calls = []

    def scope_catalog(self):
        return dict(self.scopes)

    def authorization_url(self, state, code_challenge, scopes):
        self.authorization_calls.append((state, code_challenge, tuple(scopes)))
        return "https://accounts.example.test/auth?state=%s&challenge=%s" % (
            state,
            code_challenge,
        )

    def exchange_code(self, code, verifier):
        self.exchange_calls.append((code, verifier))
        result = self.exchanges.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def revoke(self, refresh_token):
        self.revocations.append(refresh_token)
        result = self.revocations_to_return.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    revocations_to_return = None


class FakeKMS(object):
    def __init__(self):
        self.key = os.urandom(32)

    def generate_data_key(self, key_id, encryption_context, caller_identity):
        if caller_identity != INGESTION:
            raise KMSAccessDenied("denied")
        plaintext = os.urandom(32)
        wrapped = bytes(a ^ b for a, b in zip(plaintext, self.key))
        return GeneratedDataKey(plaintext, wrapped, key_id, key_id)

    def decrypt_data_key(
        self, ciphertext_blob, key_id, encryption_context, caller_identity
    ):
        if caller_identity != BROKER:
            raise KMSAccessDenied("denied")
        return bytes(a ^ b for a, b in zip(ciphertext_blob, self.key))


class MemoryVaultRepository(object):
    def __init__(self):
        self.records = {}

    def get_credential(self, credential_id):
        record = self.records.get(credential_id)
        return dict(record) if record else None

    def get_managed_oauth_credential(self, credential_id):
        record = self.get_credential(credential_id)
        if record is None:
            return None
        result = dict(record)
        result.update(json.loads(record["encrypted_data"]))
        return result

    def store_managed_oauth_credential(
        self, user_principal_id, provider, granted_scopes, envelope
    ):
        credential_id = "managed-%d" % (len(self.records) + 1)
        record = {
            "credential_id": credential_id,
            "user_principal_id": user_principal_id,
            "name": provider,
            "credential_type": "managed_oauth",
            "encrypted_data": json.dumps(
                {
                    "custody_mode": "managed_oauth",
                    "provider": provider,
                    "granted_scopes": list(granted_scopes),
                    "status": "active",
                    "envelope": envelope,
                },
                sort_keys=True,
            ),
            "nonce": "managed_oauth:v1",
            "created_at": "2026-07-29T00:00:00+00:00",
        }
        self.records[credential_id] = record
        return dict(record)

    def mark_managed_oauth_pending_revocation(self, credential_id, owner):
        record = self.records.get(credential_id)
        if record is None or record["user_principal_id"] != owner:
            return None
        payload = json.loads(record["encrypted_data"])
        payload["status"] = "pending_revocation"
        record["encrypted_data"] = json.dumps(payload, sort_keys=True)
        return self.get_managed_oauth_credential(credential_id)

    def delete_managed_oauth_credential(self, credential_id, owner):
        record = self.records.get(credential_id)
        if record is None or record["user_principal_id"] != owner:
            return False
        del self.records[credential_id]
        return True


@pytest.fixture
def oauth_stack(tmp_path):
    clock = Clock()
    sessions = SessionRepository(
        str(tmp_path / "sessions.sqlite"),
        # Keep the authenticated browser session alive beyond the OAuth
        # transaction's 10-minute TTL so this suite can isolate transaction
        # expiry from session expiry.
        idle_ttl_seconds=1200,
        absolute_ttl_seconds=3600,
    )
    transactions = OAuthRepository(str(tmp_path / "oauth.sqlite"))
    connector = FakeConnector()
    connector.revocations_to_return = []
    custody = ManagedOAuthCrypto(
        kms=FakeKMS(),
        key_id="kms-key-v1",
        ingestion_identities={INGESTION},
        broker_identity=BROKER,
    )
    vault_repository = MemoryVaultRepository()
    vault = VaultService(
        repository=vault_repository, managed_oauth_crypto=custody
    )
    service = OAuthService(
        repository=transactions,
        session_repository=sessions,
        connector=connector,
        managed_oauth_crypto=custody,
        vault_service=vault,
        clock=clock,
        ingestion_identity=INGESTION,
        broker_identity=BROKER,
    )
    try:
        yield {
            "service": service,
            "sessions": sessions,
            "transactions": transactions,
            "connector": connector,
            "vault_repository": vault_repository,
            "clock": clock,
        }
    finally:
        sessions.close()
        transactions.close()


def _session(stack, principal):
    return stack["sessions"].create(
        principal,
        proof_fingerprint="proof:%s:%d" % (
            principal,
            stack["sessions"].count_active(stack["clock"]()),
        ),
        now_ts=stack["clock"](),
    )


def _initiate(stack, session, capabilities=None, return_to="/integrations"):
    return stack["service"].initiate_google(
        session_id=session["session_id"],
        csrf_token=session["csrf_token"],
        body={
            "capabilities": capabilities or ["calendar.create", "gmail.send"],
            "return_to": return_to,
        },
    )


def _state(response):
    return parse_qs(urlsplit(response["authorization_url"]).query)["state"][0]


def authority(refresh_token="refresh-secret", scopes=()):
    return ProviderAuthority(
        access_token="access-secret",
        refresh_token=refresh_token,
        expires_in=3599,
        granted_scopes=frozenset(scopes),
    )


def test_initiation_derives_principal_from_session_and_stores_hashed_state_pkce(
    oauth_stack,
):
    session = _session(oauth_stack, "user:alice")

    status, response = _initiate(oauth_stack, session)

    assert status == 200
    state = _state(response)
    transaction = oauth_stack["transactions"].find_by_state(
        state, now_ts=oauth_stack["clock"]()
    )
    assert transaction["principal_id"] == "user:alice"
    assert transaction["expires_at"] == NOW + 600
    assert transaction["return_to"] == "/integrations"
    assert transaction["state_hash"] != state
    assert state not in json.dumps(transaction)
    assert transaction["pkce_verifier"]
    assert oauth_stack["connector"].authorization_calls[0][1] != (
        transaction["pkce_verifier"]
    )


def test_initiation_fails_without_session_csrf_or_with_unsafe_return(oauth_stack):
    session = _session(oauth_stack, "user:alice")

    status, _ = oauth_stack["service"].initiate_google(
        session_id=None,
        csrf_token=None,
        body={"capabilities": ["calendar.create"], "return_to": "/integrations"},
    )
    assert status == 401

    status, _ = oauth_stack["service"].initiate_google(
        session_id=session["session_id"],
        csrf_token="wrong",
        body={"capabilities": ["calendar.create"], "return_to": "/integrations"},
    )
    assert status == 403

    for unsafe in ("https://evil.example/capture", "//evil.example/capture", "relative"):
        status, _ = _initiate(oauth_stack, session, return_to=unsafe)
        assert status == 422
    assert oauth_stack["transactions"].count_transactions() == 0


def test_callback_consumes_once_stores_no_token_response_and_limits_capabilities(
    oauth_stack,
):
    session = _session(oauth_stack, "user:alice")
    _, initiated = _initiate(oauth_stack, session)
    state = _state(initiated)
    oauth_stack["connector"].exchanges.append(
        authority(
            scopes={"scope.calendar"}  # Gmail consent was denied.
        )
    )

    status, response = oauth_stack["service"].complete_google(
        session["session_id"], code="provider-code", state=state
    )

    assert status == 200
    assert response == {
        "result": "connected",
        "provider": "google",
        "return_to": "/integrations",
        "enabled_capabilities": ["calendar.create"],
    }
    serialized = json.dumps(response)
    assert "access-secret" not in serialized
    assert "refresh-secret" not in serialized
    assert len(oauth_stack["vault_repository"].records) == 1
    stored = next(iter(oauth_stack["vault_repository"].records.values()))
    assert "access-secret" not in stored["encrypted_data"]
    assert "refresh-secret" not in stored["encrypted_data"]

    replay_status, replay_body = oauth_stack["service"].complete_google(
        session["session_id"], code="provider-code-again", state=state
    )
    assert replay_status == 400
    assert replay_body == {"error": "invalid or consumed OAuth transaction"}
    assert len(oauth_stack["connector"].exchange_calls) == 1


def test_wrong_user_state_and_expired_transaction_store_nothing(oauth_stack):
    alice = _session(oauth_stack, "user:alice")
    bob = _session(oauth_stack, "user:bob")
    _, initiated = _initiate(oauth_stack, alice)
    state = _state(initiated)
    oauth_stack["connector"].exchanges.append(
        authority(scopes={"scope.calendar"})
    )

    status, _ = oauth_stack["service"].complete_google(
        bob["session_id"], code="code", state=state
    )
    assert status == 400
    status, _ = oauth_stack["service"].complete_google(
        alice["session_id"], code="code", state="wrong-state"
    )
    assert status == 400

    oauth_stack["clock"].value += 601
    status, _ = oauth_stack["service"].complete_google(
        alice["session_id"], code="code", state=state
    )
    assert status == 400
    assert oauth_stack["connector"].exchange_calls == []
    assert oauth_stack["vault_repository"].records == {}


def test_reconnect_without_new_refresh_token_preserves_existing_credential(
    oauth_stack,
):
    session = _session(oauth_stack, "user:alice")
    oauth_stack["connector"].exchanges.extend(
        [
            authority(
                refresh_token="original-refresh",
                scopes={"scope.calendar"},
            ),
            authority(
                refresh_token=None,
                scopes={"scope.calendar", "scope.gmail.send"},
            ),
        ]
    )

    _, first = _initiate(oauth_stack, session)
    status, _ = oauth_stack["service"].complete_google(
        session["session_id"], "code-1", _state(first)
    )
    assert status == 200
    original = oauth_stack["transactions"].get_connection(
        "user:alice", "google"
    )

    _, second = _initiate(oauth_stack, session)
    status, response = oauth_stack["service"].complete_google(
        session["session_id"], "code-2", _state(second)
    )
    assert status == 200
    current = oauth_stack["transactions"].get_connection(
        "user:alice", "google"
    )

    assert current["credential_id"] == original["credential_id"]
    assert len(oauth_stack["vault_repository"].records) == 1
    assert response["enabled_capabilities"] == [
        "calendar.create",
        "gmail.send",
    ]


def test_reconnect_with_new_refresh_token_retires_previous_credential(
    oauth_stack,
):
    session = _session(oauth_stack, "user:alice")
    oauth_stack["connector"].exchanges.extend(
        [
            authority(
                refresh_token="original-refresh",
                scopes={"scope.calendar"},
            ),
            authority(
                refresh_token="replacement-refresh",
                scopes={"scope.calendar"},
            ),
        ]
    )

    _, first = _initiate(oauth_stack, session)
    assert oauth_stack["service"].complete_google(
        session["session_id"], "code-1", _state(first)
    )[0] == 200
    original_id = oauth_stack["transactions"].get_connection(
        "user:alice", "google"
    )["credential_id"]

    _, second = _initiate(oauth_stack, session)
    assert oauth_stack["service"].complete_google(
        session["session_id"], "code-2", _state(second)
    )[0] == 200
    replacement_id = oauth_stack["transactions"].get_connection(
        "user:alice", "google"
    )["credential_id"]

    assert replacement_id != original_id
    assert original_id not in oauth_stack["vault_repository"].records
    assert replacement_id in oauth_stack["vault_repository"].records


def test_first_connect_without_refresh_token_fails_after_one_use(oauth_stack):
    session = _session(oauth_stack, "user:alice")
    _, initiated = _initiate(oauth_stack, session)
    state = _state(initiated)
    oauth_stack["connector"].exchanges.append(
        authority(refresh_token=None, scopes={"scope.calendar"})
    )

    status, response = oauth_stack["service"].complete_google(
        session["session_id"], "code", state
    )
    assert status == 502
    assert response == {"error": "Google did not grant offline access"}
    assert oauth_stack["vault_repository"].records == {}

    status, _ = oauth_stack["service"].complete_google(
        session["session_id"], "code-again", state
    )
    assert status == 400


def test_provider_failure_is_redacted_and_transaction_stays_consumed(oauth_stack):
    session = _session(oauth_stack, "user:alice")
    _, initiated = _initiate(oauth_stack, session)
    state = _state(initiated)
    oauth_stack["connector"].exchanges.append(
        ProviderNetworkError("upstream contained refresh-secret-do-not-echo")
    )

    status, response = oauth_stack["service"].complete_google(
        session["session_id"], "code", state
    )

    assert status == 502
    assert response == {"error": "Google token exchange failed"}
    status, _ = oauth_stack["service"].complete_google(
        session["session_id"], "code", state
    )
    assert status == 400


def test_disconnect_blocks_immediately_retries_and_deletes_only_after_revoke(
    oauth_stack,
):
    session = _session(oauth_stack, "user:alice")
    oauth_stack["connector"].exchanges.append(
        authority(scopes={"scope.calendar"})
    )
    _, initiated = _initiate(oauth_stack, session)
    status, _ = oauth_stack["service"].complete_google(
        session["session_id"], "code", _state(initiated)
    )
    assert status == 200
    credential_id = oauth_stack["transactions"].get_connection(
        "user:alice", "google"
    )["credential_id"]

    status, response = oauth_stack["service"].google_status(
        session["session_id"]
    )
    assert status == 200
    assert response["status"] == "connected"

    oauth_stack["connector"].revocations_to_return.extend(
        [ProviderNetworkError("refresh-secret-must-not-escape"), True]
    )
    status, response = oauth_stack["service"].disconnect_google(
        session["session_id"], session["csrf_token"]
    )

    assert status == 202
    assert response == {
        "status": "pending_revocation",
        "provider": "google",
    }
    assert "refresh-secret" not in json.dumps(response)
    assert oauth_stack["transactions"].get_connection(
        "user:alice", "google"
    )["status"] == "pending_revocation"
    assert oauth_stack["vault_repository"].get_managed_oauth_credential(
        credential_id
    )["status"] == "pending_revocation"
    with pytest.raises(PermissionError):
        oauth_stack["service"].vault_service.use_managed_oauth(
            credential_id, BROKER, lambda token: token
        )

    status, response = oauth_stack["service"].disconnect_google(
        session["session_id"], session["csrf_token"]
    )
    assert status == 200
    assert response == {"status": "disconnected", "provider": "google"}
    assert oauth_stack["connector"].revocations == [
        "refresh-secret",
        "refresh-secret",
    ]
    assert credential_id not in oauth_stack["vault_repository"].records
    assert (
        oauth_stack["transactions"].get_connection(
            "user:alice", "google"
        )
        is None
    )


def test_disconnect_requires_csrf_and_accepts_confirmed_invalid_token(
    oauth_stack,
):
    session = _session(oauth_stack, "user:alice")
    oauth_stack["connector"].exchanges.append(
        authority(scopes={"scope.calendar"})
    )
    _, initiated = _initiate(oauth_stack, session)
    oauth_stack["service"].complete_google(
        session["session_id"], "code", _state(initiated)
    )
    credential_id = oauth_stack["transactions"].get_connection(
        "user:alice", "google"
    )["credential_id"]

    status, _ = oauth_stack["service"].disconnect_google(
        session["session_id"], "wrong"
    )
    assert status == 403
    assert credential_id in oauth_stack["vault_repository"].records

    oauth_stack["connector"].revocations_to_return.append("invalid_token")
    status, response = oauth_stack["service"].disconnect_google(
        session["session_id"], session["csrf_token"]
    )
    assert status == 200
    assert response["status"] == "disconnected"
    assert credential_id not in oauth_stack["vault_repository"].records
