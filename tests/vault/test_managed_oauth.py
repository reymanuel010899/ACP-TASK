"""Threat-model tests for managed OAuth custody (U4).

AWS is represented by a contract-compatible fake.  The cryptographic path,
VaultService policy, and repository interaction are real.
"""

import json
import os

import pytest

from libs.aws_kms import GeneratedDataKey, KMSAccessDenied, KMSError
from vault.app import VaultService
from vault.managed_oauth_crypto import (
    ManagedOAuthAccessDenied,
    ManagedOAuthAuthError,
    ManagedOAuthCrypto,
    ManagedOAuthError,
)
from vault.repository import VaultRepository


BROKER = "service:credential-broker"
INGESTION = "service:oauth-ingestion"


class FakeKMS(object):
    def __init__(self):
        self.keys = {"key-v1": os.urandom(32), "key-v2": os.urandom(32)}
        self.current_key_id = "key-v1"
        self.calls = []

    def generate_data_key(self, key_id, encryption_context, caller_identity):
        self.calls.append(("generate", caller_identity, dict(encryption_context)))
        if caller_identity != INGESTION:
            raise KMSAccessDenied("GenerateDataKey denied")
        plaintext = os.urandom(32)
        return GeneratedDataKey(
            plaintext=plaintext,
            ciphertext_blob=self._wrap(plaintext, key_id),
            key_id=key_id,
            key_version=key_id,
        )

    def decrypt_data_key(
        self, ciphertext_blob, key_id, encryption_context, caller_identity
    ):
        self.calls.append(("decrypt", caller_identity, dict(encryption_context)))
        if caller_identity != BROKER:
            raise KMSAccessDenied("Decrypt denied")
        return self._unwrap(ciphertext_blob, key_id)

    def rewrap_data_key(
        self,
        ciphertext_blob,
        source_key_id,
        destination_key_id,
        encryption_context,
        caller_identity,
    ):
        self.calls.append(("rewrap", caller_identity, dict(encryption_context)))
        if caller_identity != BROKER:
            raise KMSAccessDenied("ReEncrypt denied")
        plaintext = self._unwrap(ciphertext_blob, source_key_id)
        return GeneratedDataKey(
            plaintext=None,
            ciphertext_blob=self._wrap(plaintext, destination_key_id),
            key_id=destination_key_id,
            key_version=destination_key_id,
        )

    def _wrap(self, plaintext, key_id):
        key = self.keys[key_id]
        return bytes(a ^ b for a, b in zip(plaintext, key))

    def _unwrap(self, wrapped, key_id):
        return self._wrap(wrapped, key_id)


class MemoryRepository(object):
    def __init__(self):
        self.records = {}

    def store_managed_oauth_credential(
        self, user_principal_id, provider, granted_scopes, envelope
    ):
        credential_id = "cred-%d" % (len(self.records) + 1)
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
                    "envelope": envelope,
                },
                sort_keys=True,
            ),
            "nonce": "managed_oauth:v1",
            "created_at": "2026-07-29T00:00:00+00:00",
        }
        self.records[credential_id] = record
        return dict(record)

    def get_credential(self, credential_id):
        record = self.records.get(credential_id)
        return dict(record) if record else None

    def get_managed_oauth_credential(self, credential_id):
        record = self.get_credential(credential_id)
        if not record or record["credential_type"] != "managed_oauth":
            return None
        payload = json.loads(record["encrypted_data"])
        return dict(record, **payload)

    def update_managed_oauth_envelope(self, credential_id, envelope):
        record = self.records[credential_id]
        payload = json.loads(record["encrypted_data"])
        payload["envelope"] = envelope
        record["encrypted_data"] = json.dumps(payload, sort_keys=True)
        return self.get_managed_oauth_credential(credential_id)

    def store_credential(
        self, user_principal_id, name, credential_type, encrypted_data, nonce
    ):
        credential_id = "legacy-%d" % (len(self.records) + 1)
        record = {
            "credential_id": credential_id,
            "user_principal_id": user_principal_id,
            "name": name,
            "credential_type": credential_type,
            "encrypted_data": encrypted_data,
            "nonce": nonce,
            "created_at": "2026-07-29T00:00:00+00:00",
        }
        self.records[credential_id] = record
        return dict(record)

    def get_active_grant(self, credential_id, principal_id):
        return {"scope": "read"}


@pytest.fixture
def custody():
    kms = FakeKMS()
    crypto = ManagedOAuthCrypto(
        kms=kms,
        key_id="key-v1",
        ingestion_identities={INGESTION},
        broker_identity=BROKER,
    )
    return kms, crypto


def test_only_broker_can_open_managed_oauth_and_token_never_enters_response(
    custody,
):
    _, crypto = custody
    repository = MemoryRepository()
    service = VaultService(repository=repository, managed_oauth_crypto=crypto)
    context = {"credential_id": "pending-1", "user_principal_id": "user:alice"}
    envelope = crypto.seal(
        b"google-refresh-token-secret",
        encryption_context=context,
        caller_identity=INGESTION,
    )

    status, response = service.store_managed_oauth(
        {
            "user_principal_id": "user:alice",
            "provider": "google",
            "granted_scopes": ["calendar.events"],
            "envelope": envelope,
        },
        signer="user:alice",
    )
    assert status == 200
    serialized = json.dumps(response)
    assert "google-refresh-token-secret" not in serialized
    assert "ciphertext" not in response
    credential_id = response["credential_id"]

    observed = service.use_managed_oauth(
        credential_id,
        service_identity=BROKER,
        operation=lambda token: token.startswith(b"google-refresh"),
    )
    assert observed is True

    for unauthorized in (
        "user:alice",
        "agent:calendar",
        "service:verifier",
        "service:orchestrator",
    ):
        with pytest.raises(ManagedOAuthAccessDenied):
            service.use_managed_oauth(
                credential_id,
                service_identity=unauthorized,
                operation=lambda token: token,
            )


def test_ciphertext_tampering_fails_authenticated_decryption(custody):
    _, crypto = custody
    context = {"credential_id": "cred-1", "user_principal_id": "user:alice"}
    envelope = crypto.seal(
        b"refresh-secret", context, caller_identity=INGESTION
    )
    raw = bytearray(crypto.decode_field(envelope["ciphertext"]))
    raw[0] ^= 0x01
    envelope["ciphertext"] = crypto.encode_field(bytes(raw))

    with pytest.raises(ManagedOAuthAuthError):
        crypto.open(envelope, context, caller_identity=BROKER)


def test_kms_outage_is_reported_as_managed_oauth_failure():
    class UnavailableKMS(object):
        def generate_data_key(
            self, key_id, encryption_context, caller_identity
        ):
            raise KMSError("AWS KMS operation failed")

    crypto = ManagedOAuthCrypto(
        kms=UnavailableKMS(),
        key_id="key-v1",
        ingestion_identities={INGESTION},
        broker_identity=BROKER,
    )

    with pytest.raises(ManagedOAuthError, match="KMS GenerateDataKey unavailable"):
        crypto.seal(
            b"refresh-secret",
            {"user_principal_id": "user:alice"},
            caller_identity=INGESTION,
        )


def test_key_rotation_rewraps_without_reencrypting_token_ciphertext(custody):
    _, crypto = custody
    context = {"credential_id": "cred-1", "user_principal_id": "user:alice"}
    envelope = crypto.seal(
        b"refresh-secret", context, caller_identity=INGESTION
    )
    original_ciphertext = envelope["ciphertext"]

    rotated = crypto.rewrap(
        envelope,
        destination_key_id="key-v2",
        encryption_context=context,
        caller_identity=BROKER,
    )

    assert rotated["ciphertext"] == original_ciphertext
    assert rotated["kms_key_id"] == "key-v2"
    assert crypto.open(rotated, context, caller_identity=BROKER) == (
        b"refresh-secret"
    )


def test_generic_agent_access_never_returns_managed_blob_and_legacy_is_unchanged(
    custody,
):
    _, crypto = custody
    repository = MemoryRepository()
    service = VaultService(repository=repository, managed_oauth_crypto=crypto)
    context = {"credential_id": "pending-1", "user_principal_id": "user:alice"}
    envelope = crypto.seal(
        b"refresh-secret", context, caller_identity=INGESTION
    )
    _, managed = service.store_managed_oauth(
        {
            "user_principal_id": "user:alice",
            "provider": "google",
            "granted_scopes": [],
            "envelope": envelope,
        },
        signer="user:alice",
    )

    status, response = service.request_access(
        managed["credential_id"],
        {"agent_principal_id": "agent:any"},
        signer="agent:any",
    )
    assert status == 403
    assert response == {"access_granted": False}

    legacy = repository.store_credential(
        "user:alice", "legacy", "api_key", "legacy-ciphertext", "legacy-nonce"
    )
    status, response = service.request_access(
        legacy["credential_id"],
        {"agent_principal_id": "agent:any"},
        signer="agent:any",
    )
    assert status == 200
    assert response["encrypted_data"] == "legacy-ciphertext"
    assert response["nonce"] == "legacy-nonce"


def test_real_repository_round_trips_envelope_as_managed_not_zero_knowledge(
    custody,
):
    _, crypto = custody
    repository = VaultRepository()
    context = {
        "credential_id": "binding-real-repository",
        "user_principal_id": "user:repository-managed",
    }
    envelope = crypto.seal(
        b"repository-refresh-secret",
        context,
        caller_identity=INGESTION,
    )

    stored = repository.store_managed_oauth_credential(
        "user:repository-managed",
        "google",
        ["calendar.events"],
        envelope,
    )
    fetched = repository.get_managed_oauth_credential(stored["credential_id"])

    assert fetched["custody_mode"] == "managed_oauth"
    assert fetched["provider"] == "google"
    assert fetched["granted_scopes"] == ["calendar.events"]
    assert fetched["envelope"] == envelope
