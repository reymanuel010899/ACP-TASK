"""Tests for the Vault service keyring + credential storage (unit U7).

Boots the vault server and drives it over HTTP via VaultClient, exactly as a
client device would: register keyring, fetch from another device, unlock,
rotate password, store credentials.
"""

import os
import threading

import pytest
import requests

from libs.vault_client import VaultClient
from vault import crypto
from vault.app import make_server

TEST_ITERATIONS = 1000


def base_url(server):
    host, port = server.server_address[:2]
    return "http://%s:%d" % (host, port)


@pytest.fixture
def vault():
    server = make_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def client(vault):
    return VaultClient(base_url(vault))


def test_healthz(vault):
    resp = requests.get(base_url(vault) + "/healthz", timeout=5)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# Scenario 4: multi-device login via wrapped keyring -------------------------


def test_store_keyring_then_unlock_from_another_device(client, vault):
    private_key = os.urandom(32)
    dek, resp = client.register_user_keyring(
        "master-pw", "ed25519_alice", private_key, iterations=TEST_ITERATIONS
    )
    assert resp["user_principal_id"] == "ed25519_alice"
    assert "created_at" in resp

    # "Another device": fresh client, only knows password + principal id
    other_device = VaultClient(base_url(vault))
    blob = other_device.fetch_keyring("ed25519_alice")
    dek2, private_key2 = other_device.unlock_keyring("master-pw", blob)
    assert dek2 == dek
    assert private_key2 == private_key


def test_fetch_keyring_unknown_user_404(client):
    with pytest.raises(requests.HTTPError) as excinfo:
        client.fetch_keyring("ed25519_nobody")
    assert excinfo.value.response.status_code == 404


# Scenario 5: wrong password -> auth failure, no partial data ----------------


def test_unlock_with_wrong_password_fails(client):
    client.register_user_keyring(
        "master-pw", "ed25519_bob", os.urandom(32), iterations=TEST_ITERATIONS
    )
    blob = client.fetch_keyring("ed25519_bob")
    with pytest.raises(crypto.VaultAuthError):
        client.unlock_keyring("wrong-pw", blob)


# Scenario 7: unknown kdf rejected with 422 ----------------------------------


def test_store_keyring_unknown_kdf_rejected_422(client, vault):
    blob, _dek = crypto.build_keyring_blob(
        "pw", os.urandom(32), iterations=TEST_ITERATIONS
    )
    blob["kdf"] = "argon2id"
    blob["user_principal_id"] = "ed25519_carol"
    resp = requests.post(
        base_url(vault) + "/keyring", json=blob, timeout=5
    )
    assert resp.status_code == 422
    # Nothing stored under that principal
    assert (
        requests.get(
            base_url(vault) + "/keyring/ed25519_carol", timeout=5
        ).status_code
        == 404
    )


# Scenario 6: password change re-wraps DEK, data never re-encrypted ----------


def test_password_change_rewraps_dek_credentials_still_decryptable(client):
    user = "ed25519_dana"
    dek, _ = client.register_user_keyring(
        "old-pw", user, os.urandom(32), iterations=TEST_ITERATIONS
    )

    # Store a credential encrypted under the DEK
    ciphertext, nonce = crypto.encrypt_data(b'{"token": "gh_abc"}', dek)
    cred = client.store_credential(
        user, "github", "api_token", ciphertext, nonce
    )
    assert cred["credential_id"]

    # Change password: re-wrap the SAME DEK under a new KEK
    client.change_password(
        user, "old-pw", "new-pw",
        rotation_reason="user password change",
        iterations=TEST_ITERATIONS,
    )

    blob = client.fetch_keyring(user)
    with pytest.raises(crypto.VaultAuthError):
        client.unlock_keyring("old-pw", blob)

    dek2, _pk = client.unlock_keyring("new-pw", blob)
    assert dek2 == dek  # same DEK -> stored ciphertexts never re-encrypted
    assert crypto.decrypt_data(ciphertext, nonce, dek2) == b'{"token": "gh_abc"}'


def test_rotate_keyring_unknown_user_404(client):
    blob, _dek = crypto.build_keyring_blob(
        "pw", os.urandom(32), iterations=TEST_ITERATIONS
    )
    with pytest.raises(requests.HTTPError) as excinfo:
        client.rotate_keyring("ed25519_ghost", blob, "compromise suspected")
    assert excinfo.value.response.status_code == 404


# Scenario 13: rotation logs audit event with reason -------------------------


def test_rotation_logs_audit_event_with_reason(client, vault):
    user = "ed25519_erin"
    client.register_user_keyring(
        "pw-1", user, os.urandom(32), iterations=TEST_ITERATIONS
    )
    client.change_password(
        user, "pw-1", "pw-2",
        rotation_reason="suspected phishing",
        iterations=TEST_ITERATIONS,
    )

    resp = requests.get(
        base_url(vault) + "/audit", params={"principal_id": user}, timeout=5
    )
    assert resp.status_code == 200
    entries = resp.json()["entries"]
    rotations = [e for e in entries if e["action"] == "keyring_rotated"]
    assert len(rotations) == 1
    entry = rotations[0]
    assert entry["principal_id"] == user
    assert entry["reason"] == "suspected phishing"
    assert "timestamp" in entry


# Scenario 8: credential upload + metadata-only listing ----------------------


def test_store_credential_and_list_metadata_only(client):
    user = "ed25519_frank"
    dek, _ = client.register_user_keyring(
        "pw", user, os.urandom(32), iterations=TEST_ITERATIONS
    )
    ciphertext, nonce = crypto.encrypt_data(b"sk-live-999", dek)
    resp = client.store_credential(
        user, "stripe key", "api_key", ciphertext, nonce
    )
    assert resp["credential_id"]
    assert "created_at" in resp

    listing = client.list_credentials(user)
    assert len(listing) == 1
    item = listing[0]
    assert item["credential_id"] == resp["credential_id"]
    assert item["name"] == "stripe key"
    assert item["credential_type"] == "api_key"
    assert item["user_principal_id"] == user
    # Zero-knowledge listing: no ciphertext or nonce leaked
    assert "encrypted_data" not in item
    assert "nonce" not in item


def test_list_credentials_scoped_to_user(client):
    dek_a, _ = client.register_user_keyring(
        "pw-a", "ed25519_gina", os.urandom(32), iterations=TEST_ITERATIONS
    )
    dek_b, _ = client.register_user_keyring(
        "pw-b", "ed25519_hank", os.urandom(32), iterations=TEST_ITERATIONS
    )
    ct_a, n_a = crypto.encrypt_data(b"a", dek_a)
    ct_b, n_b = crypto.encrypt_data(b"b", dek_b)
    client.store_credential("ed25519_gina", "cred-a", "password", ct_a, n_a)
    client.store_credential("ed25519_hank", "cred-b", "password", ct_b, n_b)

    names = [c["name"] for c in client.list_credentials("ed25519_gina")]
    assert names == ["cred-a"]


def test_store_credential_missing_fields_422(vault):
    resp = requests.post(
        base_url(vault) + "/credentials",
        json={"name": "incomplete"},
        timeout=5,
    )
    assert resp.status_code == 422
