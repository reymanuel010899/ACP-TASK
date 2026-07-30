"""Managed OAuth revocation lifecycle tests (U5)."""

import json
import os

import pytest

from libs.aws_kms import GeneratedDataKey, KMSAccessDenied
from vault.app import VaultService
from vault.managed_oauth_crypto import ManagedOAuthCrypto


BROKER = "service:credential-broker"
INGESTION = "service:oauth-ingestion"


class FakeKMS(object):
    def __init__(self):
        self.key = os.urandom(32)

    def generate_data_key(self, key_id, context, caller_identity):
        if caller_identity != INGESTION:
            raise KMSAccessDenied("denied")
        plaintext = os.urandom(32)
        wrapped = bytes(a ^ b for a, b in zip(plaintext, self.key))
        return GeneratedDataKey(plaintext, wrapped, key_id, key_id)

    def decrypt_data_key(self, wrapped, key_id, context, caller_identity):
        if caller_identity != BROKER:
            raise KMSAccessDenied("denied")
        return bytes(a ^ b for a, b in zip(wrapped, self.key))


class MemoryRepository(object):
    def __init__(self):
        self.credentials = {}
        self.grants = {"cred-1": ["grant-1"]}

    def get_credential(self, credential_id):
        record = self.credentials.get(credential_id)
        return dict(record) if record else None

    def get_managed_oauth_credential(self, credential_id):
        record = self.get_credential(credential_id)
        if not record:
            return None
        return dict(record, **json.loads(record["encrypted_data"]))

    def mark_managed_oauth_pending_revocation(self, credential_id, owner):
        record = self.credentials.get(credential_id)
        if not record or record["user_principal_id"] != owner:
            return None
        payload = json.loads(record["encrypted_data"])
        payload["status"] = "pending_revocation"
        record["encrypted_data"] = json.dumps(payload, sort_keys=True)
        return self.get_managed_oauth_credential(credential_id)

    def delete_managed_oauth_credential(self, credential_id, owner):
        record = self.credentials.get(credential_id)
        if not record or record["user_principal_id"] != owner:
            return False
        self.grants.pop(credential_id, None)
        del self.credentials[credential_id]
        return True


@pytest.fixture
def vault():
    kms = FakeKMS()
    crypto = ManagedOAuthCrypto(
        kms,
        "key-v1",
        ingestion_identities={INGESTION},
        broker_identity=BROKER,
    )
    context = {"credential_id": "cred-1", "user_principal_id": "user:alice"}
    envelope = crypto.seal(
        b"google-refresh-secret", context, caller_identity=INGESTION
    )
    repository = MemoryRepository()
    repository.credentials["cred-1"] = {
        "credential_id": "cred-1",
        "user_principal_id": "user:alice",
        "credential_type": "managed_oauth",
        "encrypted_data": json.dumps(
            {
                "custody_mode": "managed_oauth",
                "provider": "google",
                "granted_scopes": ["scope.calendar"],
                "status": "active",
                "envelope": envelope,
            },
            sort_keys=True,
        ),
    }
    return VaultService(repository=repository, managed_oauth_crypto=crypto), repository


def test_owner_marks_pending_before_provider_call_and_use_is_blocked(vault):
    service, repository = vault
    observed = []

    status, _ = service.begin_managed_oauth_revocation(
        "cred-1", "user:alice"
    )
    assert status == 200
    assert repository.get_managed_oauth_credential("cred-1")["status"] == (
        "pending_revocation"
    )

    with pytest.raises(PermissionError):
        service.use_managed_oauth(
            "cred-1", BROKER, operation=lambda token: observed.append(token)
        )
    assert observed == []


def test_non_owner_cannot_start_or_finish_revocation(vault):
    service, repository = vault
    status, _ = service.begin_managed_oauth_revocation("cred-1", "user:bob")
    assert status == 403
    assert repository.get_managed_oauth_credential("cred-1")["status"] == "active"

    assert (
        service.delete_managed_oauth_credential("cred-1", "user:bob") == 403
    )
    assert "cred-1" in repository.credentials


def test_broker_callback_receives_token_but_response_does_not(vault):
    service, _ = vault
    service.begin_managed_oauth_revocation("cred-1", "user:alice")

    result = service.revoke_managed_oauth(
        "cred-1",
        BROKER,
        operation=lambda token: token == b"google-refresh-secret",
    )

    assert result is True
    assert "google-refresh-secret" not in json.dumps({"result": result})


def test_delete_removes_credential_and_grants_only_after_confirmation(vault):
    service, repository = vault
    service.begin_managed_oauth_revocation("cred-1", "user:alice")

    assert "cred-1" in repository.credentials
    assert "cred-1" in repository.grants
    assert service.delete_managed_oauth_credential(
        "cred-1", "user:alice"
    ) == 200
    assert "cred-1" not in repository.credentials
    assert "cred-1" not in repository.grants
