"""Tests for vault/crypto.py — envelope encryption primitives (Decision 8).

Chain: Master Password -> PBKDF2-SHA256 -> KEK -> wraps DEK -> encrypts data.
Uses reduced iteration counts (1000) where the exact value is not the contract;
the default-iterations contract (600,000) is asserted explicitly.
"""

import inspect
import os

import pytest

from vault import crypto
from vault.crypto import (
    DEFAULT_ITERATIONS,
    DEFAULT_KDF,
    UnsupportedKDFError,
    VaultAuthError,
    build_keyring_blob,
    decrypt_data,
    derive_kek,
    encrypt_data,
    generate_dek,
    generate_salt,
    unlock_keyring_blob,
    unwrap_dek,
    validate_kdf,
    wrap_dek,
)

TEST_ITERATIONS = 1000  # fast; the KDF contract value is tested separately


# Scenario 1: derive_kek determinism -----------------------------------------


def test_derive_kek_deterministic_same_password_and_salt():
    salt = b"\x01" * 16
    kek1 = derive_kek("hunter2", salt, iterations=TEST_ITERATIONS)
    kek2 = derive_kek("hunter2", salt, iterations=TEST_ITERATIONS)
    assert kek1 == kek2
    assert isinstance(kek1, bytes)
    assert len(kek1) == 32


def test_derive_kek_different_salt_gives_different_kek():
    kek1 = derive_kek("hunter2", b"\x01" * 16, iterations=TEST_ITERATIONS)
    kek2 = derive_kek("hunter2", b"\x02" * 16, iterations=TEST_ITERATIONS)
    assert kek1 != kek2


def test_derive_kek_different_password_gives_different_kek():
    salt = b"\x03" * 16
    assert derive_kek("a", salt, iterations=TEST_ITERATIONS) != derive_kek(
        "b", salt, iterations=TEST_ITERATIONS
    )


def test_default_kdf_iterations_is_600000():
    """Decision 8 contract: PBKDF2-SHA256 with 600,000 iterations by default."""
    assert DEFAULT_ITERATIONS == 600000
    assert DEFAULT_KDF == "pbkdf2-sha256"
    sig = inspect.signature(derive_kek)
    assert sig.parameters["iterations"].default == 600000


# Scenario 2: wrap/unwrap DEK ------------------------------------------------


def test_wrap_unwrap_dek_roundtrip():
    kek = derive_kek("correct horse", generate_salt(), iterations=TEST_ITERATIONS)
    dek = generate_dek()
    encrypted_dek, nonce = wrap_dek(dek, kek)
    assert encrypted_dek != dek
    assert unwrap_dek(encrypted_dek, nonce, kek) == dek


def test_unwrap_dek_with_wrong_password_kek_raises_auth_error():
    """Authenticated encryption: wrong KEK must fail loudly, never emit garbage."""
    salt = generate_salt()
    good_kek = derive_kek("right password", salt, iterations=TEST_ITERATIONS)
    bad_kek = derive_kek("wrong password", salt, iterations=TEST_ITERATIONS)
    dek = generate_dek()
    encrypted_dek, nonce = wrap_dek(dek, good_kek)
    with pytest.raises(VaultAuthError):
        unwrap_dek(encrypted_dek, nonce, bad_kek)


def test_decrypt_tampered_ciphertext_raises_auth_error():
    dek = generate_dek()
    ciphertext, nonce = encrypt_data(b"secret-api-key", dek)
    tampered = bytes([ciphertext[0] ^ 0xFF]) + ciphertext[1:]
    with pytest.raises(VaultAuthError):
        decrypt_data(tampered, nonce, dek)


# Scenario 3: full envelope roundtrip ----------------------------------------


def test_envelope_roundtrip_password_to_credential():
    """password -> KEK -> DEK -> encrypt credential -> decrypt via full chain."""
    password = "s3cret master pw"
    salt = generate_salt()

    # Wrap side
    kek = derive_kek(password, salt, iterations=TEST_ITERATIONS)
    dek = generate_dek()
    encrypted_dek, dek_nonce = wrap_dek(dek, kek)
    credential = b'{"api_key": "sk-live-12345"}'
    ciphertext, cred_nonce = encrypt_data(credential, dek)

    # Unwrap side: only password + stored blobs
    kek2 = derive_kek(password, salt, iterations=TEST_ITERATIONS)
    dek2 = unwrap_dek(encrypted_dek, dek_nonce, kek2)
    assert decrypt_data(ciphertext, cred_nonce, dek2) == credential


# Keyring blob helpers (client-side envelope work) ---------------------------


def test_build_and_unlock_keyring_blob_roundtrip():
    private_key = os.urandom(32)
    blob, dek = build_keyring_blob(
        "master-pw", private_key, iterations=TEST_ITERATIONS
    )
    # Blob must carry KDF metadata for forward compatibility
    assert blob["kdf"] == "pbkdf2-sha256"
    assert blob["kdf_params"] == {"iterations": TEST_ITERATIONS}
    for field in ("encrypted_dek", "salt", "nonce", "encrypted_private_key"):
        assert isinstance(blob[field], str)  # JSON-safe (base64)

    dek2, private_key2 = unlock_keyring_blob("master-pw", blob)
    assert dek2 == dek
    assert private_key2 == private_key


def test_unlock_keyring_blob_wrong_password_raises_no_partial_data():
    blob, _dek = build_keyring_blob(
        "master-pw", os.urandom(32), iterations=TEST_ITERATIONS
    )
    with pytest.raises(VaultAuthError):
        unlock_keyring_blob("not-the-password", blob)


def test_build_keyring_blob_default_iterations():
    blob, _dek = build_keyring_blob("pw", os.urandom(32))
    assert blob["kdf_params"]["iterations"] == 600000


# Scenario 7 (crypto level): unknown kdf metadata rejected -------------------


def test_validate_kdf_accepts_known():
    validate_kdf("pbkdf2-sha256", {"iterations": 600000})


def test_validate_kdf_rejects_unknown_kdf():
    with pytest.raises(UnsupportedKDFError):
        validate_kdf("argon2id", {"iterations": 3})


def test_validate_kdf_rejects_bad_params():
    with pytest.raises(UnsupportedKDFError):
        validate_kdf("pbkdf2-sha256", {})
    with pytest.raises(UnsupportedKDFError):
        validate_kdf("pbkdf2-sha256", {"iterations": "lots"})


def test_unlock_keyring_blob_unknown_kdf_rejected():
    blob, _dek = build_keyring_blob(
        "pw", os.urandom(32), iterations=TEST_ITERATIONS
    )
    blob["kdf"] = "scrypt"
    with pytest.raises(UnsupportedKDFError):
        unlock_keyring_blob("pw", blob)
