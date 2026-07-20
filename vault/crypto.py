"""Envelope encryption primitives for the AgentTrust Vault (Decision 8).

Chain:
    Master Password -> PBKDF2-SHA256 (600,000 iterations, client-side) -> KEK
    KEK wraps -> DEK (per-user Data Encryption Key, stored ENCRYPTED)
    DEK encrypts -> credentials + principal private key

The KEK is never stored anywhere; it exists only transiently on the client.
The Vault service stores only wrapped blobs (zero-knowledge). All symmetric
encryption uses PyNaCl's SecretBox (XSalsa20-Poly1305), an AEAD construction:
decryption with the wrong key raises an authentication error instead of
returning garbage.

These helpers are used client-side (by libs/vault_client.py and tests); the
server never sees passwords, KEKs, or plaintext DEKs.
"""

import base64
import hashlib
import os

import nacl.exceptions
import nacl.secret
import nacl.utils

DEFAULT_KDF = "pbkdf2-sha256"
DEFAULT_ITERATIONS = 600000
KEY_SIZE = nacl.secret.SecretBox.KEY_SIZE  # 32
NONCE_SIZE = nacl.secret.SecretBox.NONCE_SIZE  # 24
SALT_SIZE = 16

SUPPORTED_KDFS = (DEFAULT_KDF,)


class VaultCryptoError(Exception):
    """Base class for vault crypto errors."""


class VaultAuthError(VaultCryptoError):
    """Decryption failed authentication (wrong password/key or tampering)."""


class UnsupportedKDFError(VaultCryptoError):
    """Keyring blob declares a KDF this implementation does not support."""


# ---------------------------------------------------------------------------
# Encoding helpers (blobs travel as JSON, so bytes are base64 strings)
# ---------------------------------------------------------------------------


def b64encode(raw):
    # type: (bytes) -> str
    return base64.b64encode(raw).decode("ascii")


def b64decode(text):
    # type: (str) -> bytes
    return base64.b64decode(text.encode("ascii"))


# ---------------------------------------------------------------------------
# KDF
# ---------------------------------------------------------------------------


def validate_kdf(kdf, kdf_params):
    # type: (str, dict) -> None
    """Validate KDF metadata from a keyring blob (forward-compat check).

    Raises UnsupportedKDFError for unknown kdf values or malformed params,
    so that blobs written by a future Vault version are rejected loudly
    instead of being mis-derived.
    """
    if kdf not in SUPPORTED_KDFS:
        raise UnsupportedKDFError(
            "unsupported kdf %r (supported: %s)"
            % (kdf, ", ".join(SUPPORTED_KDFS))
        )
    if not isinstance(kdf_params, dict):
        raise UnsupportedKDFError("kdf_params must be an object")
    iterations = kdf_params.get("iterations")
    if not isinstance(iterations, int) or iterations < 1:
        raise UnsupportedKDFError(
            "kdf_params.iterations must be a positive integer"
        )


def derive_kek(password, salt, iterations=DEFAULT_ITERATIONS):
    # type: (str, bytes, int) -> bytes
    """Derive the Key Encryption Key from the master password.

    Deterministic for the same (password, salt, iterations). The KEK must
    never be stored — derive it on demand, use it, discard it.
    """
    if isinstance(password, str):
        password = password.encode("utf-8")
    return hashlib.pbkdf2_hmac(
        "sha256", password, salt, iterations, dklen=KEY_SIZE
    )


def generate_salt():
    # type: () -> bytes
    return os.urandom(SALT_SIZE)


def generate_dek():
    # type: () -> bytes
    """Generate a fresh per-user Data Encryption Key."""
    return nacl.utils.random(KEY_SIZE)


# ---------------------------------------------------------------------------
# Authenticated encryption (XSalsa20-Poly1305)
# ---------------------------------------------------------------------------


def _seal(plaintext, key):
    # type: (bytes, bytes) -> tuple
    nonce = nacl.utils.random(NONCE_SIZE)
    box = nacl.secret.SecretBox(key)
    ciphertext = box.encrypt(plaintext, nonce).ciphertext
    return ciphertext, nonce


def _open(ciphertext, nonce, key):
    # type: (bytes, bytes, bytes) -> bytes
    box = nacl.secret.SecretBox(key)
    try:
        return box.decrypt(ciphertext, nonce)
    except nacl.exceptions.CryptoError as exc:
        raise VaultAuthError(
            "decryption failed: wrong key or tampered ciphertext"
        ) from exc


def wrap_dek(dek, kek):
    # type: (bytes, bytes) -> tuple
    """Encrypt the DEK under the KEK. Returns (encrypted_dek, nonce)."""
    return _seal(dek, kek)


def unwrap_dek(encrypted_dek, nonce, kek):
    # type: (bytes, bytes, bytes) -> bytes
    """Recover the DEK. Raises VaultAuthError if the KEK is wrong."""
    return _open(encrypted_dek, nonce, kek)


def encrypt_data(plaintext, dek):
    # type: (bytes, bytes) -> tuple
    """Encrypt credential/key material under the DEK. Returns (ct, nonce)."""
    return _seal(plaintext, dek)


def decrypt_data(ciphertext, nonce, dek):
    # type: (bytes, bytes, bytes) -> bytes
    """Decrypt data. Raises VaultAuthError on wrong DEK or tampering."""
    return _open(ciphertext, nonce, dek)


# ---------------------------------------------------------------------------
# Keyring blob helpers (the client-side envelope work)
# ---------------------------------------------------------------------------


def build_keyring_blob(password, private_key, iterations=DEFAULT_ITERATIONS):
    # type: (str, bytes, int) -> tuple
    """Build the wrapped keyring blob stored in the Vault.

    Returns (blob, dek). The blob is JSON-safe (bytes are base64) and
    contains only wrapped material:
        {encrypted_dek, salt, nonce, kdf, kdf_params, encrypted_private_key}
    The private key is encrypted under the DEK with its own nonce, stored
    combined as nonce||ciphertext inside encrypted_private_key.
    """
    salt = generate_salt()
    kek = derive_kek(password, salt, iterations=iterations)
    dek = generate_dek()
    encrypted_dek, nonce = wrap_dek(dek, kek)
    pk_ciphertext, pk_nonce = encrypt_data(private_key, dek)
    blob = {
        "encrypted_dek": b64encode(encrypted_dek),
        "salt": b64encode(salt),
        "nonce": b64encode(nonce),
        "kdf": DEFAULT_KDF,
        "kdf_params": {"iterations": iterations},
        "encrypted_private_key": b64encode(pk_nonce + pk_ciphertext),
    }
    return blob, dek


def rewrap_keyring_blob(dek, new_password, encrypted_private_key,
                        iterations=DEFAULT_ITERATIONS):
    # type: (bytes, str, str, int) -> dict
    """Re-wrap an existing DEK under a KEK derived from a new password.

    The DEK (and therefore every ciphertext encrypted under it, including
    the principal private key) is unchanged — only the wrapping changes.
    """
    salt = generate_salt()
    kek = derive_kek(new_password, salt, iterations=iterations)
    encrypted_dek, nonce = wrap_dek(dek, kek)
    return {
        "encrypted_dek": b64encode(encrypted_dek),
        "salt": b64encode(salt),
        "nonce": b64encode(nonce),
        "kdf": DEFAULT_KDF,
        "kdf_params": {"iterations": iterations},
        "encrypted_private_key": encrypted_private_key,
    }


def unlock_keyring_blob(password, blob):
    # type: (str, dict) -> tuple
    """Unlock a fetched keyring blob with the master password.

    Returns (dek, private_key). Raises VaultAuthError on a wrong password
    (authenticated encryption — no partial/garbage data is ever returned)
    and UnsupportedKDFError for blobs written with an unknown KDF.
    """
    validate_kdf(blob.get("kdf"), blob.get("kdf_params"))
    iterations = blob["kdf_params"]["iterations"]
    salt = b64decode(blob["salt"])
    kek = derive_kek(password, salt, iterations=iterations)
    dek = unwrap_dek(
        b64decode(blob["encrypted_dek"]), b64decode(blob["nonce"]), kek
    )
    combined = b64decode(blob["encrypted_private_key"])
    pk_nonce, pk_ciphertext = combined[:NONCE_SIZE], combined[NONCE_SIZE:]
    private_key = decrypt_data(pk_ciphertext, pk_nonce, dek)
    return dek, private_key
