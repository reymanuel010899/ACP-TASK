"""Server-managed envelope encryption for OAuth token material."""

import base64
import json

import nacl.exceptions
import nacl.secret
import nacl.utils

from libs.aws_kms import KMSAccessDenied, KMSError


class ManagedOAuthError(Exception):
    """Base class for managed OAuth custody failures."""


class ManagedOAuthAccessDenied(ManagedOAuthError):
    """The service identity is not authorized for this custody operation."""


class ManagedOAuthAuthError(ManagedOAuthError):
    """Envelope authentication failed; ciphertext or context was altered."""


class ManagedOAuthCrypto(object):
    VERSION = 1

    def __init__(
        self, kms, key_id, ingestion_identities, broker_identity
    ):
        if not key_id or not broker_identity:
            raise ValueError("KMS key id and broker identity are required")
        self.kms = kms
        self.key_id = key_id
        self.ingestion_identities = frozenset(ingestion_identities)
        self.broker_identity = broker_identity

    def seal(self, plaintext, encryption_context, caller_identity):
        if caller_identity not in self.ingestion_identities:
            raise ManagedOAuthAccessDenied("OAuth ingestion identity required")
        return self._seal(plaintext, encryption_context, caller_identity)

    def seal_rotation_document(
        self, document, encryption_context, caller_identity
    ):
        if caller_identity != self.broker_identity:
            raise ManagedOAuthAccessDenied("credential broker identity required")
        plaintext = json.dumps(
            document, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return self._seal(plaintext, encryption_context, caller_identity)

    def _seal(self, plaintext, encryption_context, caller_identity):
        if isinstance(plaintext, str):
            plaintext = plaintext.encode("utf-8")
        try:
            data_key = self.kms.generate_data_key(
                self.key_id, encryption_context, caller_identity
            )
        except KMSAccessDenied as exc:
            raise ManagedOAuthAccessDenied("KMS GenerateDataKey denied") from exc
        except KMSError as exc:
            raise ManagedOAuthError("KMS GenerateDataKey unavailable") from exc
        if not data_key.plaintext:
            raise ManagedOAuthAuthError("KMS did not return a plaintext data key")
        nonce = nacl.utils.random(nacl.secret.SecretBox.NONCE_SIZE)
        ciphertext = nacl.secret.SecretBox(data_key.plaintext).encrypt(
            plaintext, nonce
        ).ciphertext
        return {
            "version": self.VERSION,
            "algorithm": "XSalsa20-Poly1305",
            "encryption_context": dict(encryption_context),
            "ciphertext": self.encode_field(ciphertext),
            "nonce": self.encode_field(nonce),
            "wrapped_data_key": self.encode_field(data_key.ciphertext_blob),
            "kms_key_id": data_key.key_id,
            "kms_key_version": data_key.key_version,
        }

    def open(self, envelope, encryption_context, caller_identity):
        if caller_identity != self.broker_identity:
            raise ManagedOAuthAccessDenied("credential broker identity required")
        self._validate(envelope)
        if dict(encryption_context) != envelope["encryption_context"]:
            raise ManagedOAuthAuthError(
                "managed OAuth encryption context does not match"
            )
        try:
            data_key = self.kms.decrypt_data_key(
                self.decode_field(envelope["wrapped_data_key"]),
                envelope["kms_key_id"],
                encryption_context,
                caller_identity,
            )
        except KMSAccessDenied as exc:
            raise ManagedOAuthAccessDenied("KMS Decrypt denied") from exc
        try:
            return nacl.secret.SecretBox(data_key).decrypt(
                self.decode_field(envelope["ciphertext"]),
                self.decode_field(envelope["nonce"]),
            )
        except (nacl.exceptions.CryptoError, ValueError, TypeError) as exc:
            raise ManagedOAuthAuthError(
                "managed OAuth ciphertext or context failed authentication"
            ) from exc

    def rewrap(
        self,
        envelope,
        destination_key_id,
        encryption_context,
        caller_identity,
    ):
        if caller_identity != self.broker_identity:
            raise ManagedOAuthAccessDenied("credential broker identity required")
        self._validate(envelope)
        if dict(encryption_context) != envelope["encryption_context"]:
            raise ManagedOAuthAuthError(
                "managed OAuth encryption context does not match"
            )
        try:
            rewrapped = self.kms.rewrap_data_key(
                self.decode_field(envelope["wrapped_data_key"]),
                envelope["kms_key_id"],
                destination_key_id,
                encryption_context,
                caller_identity,
            )
        except KMSAccessDenied as exc:
            raise ManagedOAuthAccessDenied("KMS ReEncrypt denied") from exc
        updated = dict(envelope)
        updated.update(
            {
                "wrapped_data_key": self.encode_field(
                    rewrapped.ciphertext_blob
                ),
                "kms_key_id": rewrapped.key_id,
                "kms_key_version": rewrapped.key_version,
            }
        )
        return updated

    @staticmethod
    def encode_field(value):
        return base64.b64encode(value).decode("ascii")

    @staticmethod
    def decode_field(value):
        return base64.b64decode(value.encode("ascii"), validate=True)

    def _validate(self, envelope):
        validate_managed_oauth_envelope(envelope)


def validate_managed_oauth_envelope(envelope):
    """Validate the versioned storage shape without invoking KMS."""
    if (
        not isinstance(envelope, dict)
        or envelope.get("version") != ManagedOAuthCrypto.VERSION
    ):
        raise ManagedOAuthAuthError("unsupported managed OAuth envelope")
    for field in (
        "encryption_context",
        "ciphertext",
        "nonce",
        "wrapped_data_key",
        "kms_key_id",
        "kms_key_version",
    ):
        if not envelope.get(field):
            raise ManagedOAuthAuthError(
                "managed OAuth envelope missing %s" % field
            )
    if not isinstance(envelope["encryption_context"], dict):
        raise ManagedOAuthAuthError(
            "managed OAuth encryption context must be an object"
        )
    for field in ("ciphertext", "nonce", "wrapped_data_key"):
        try:
            ManagedOAuthCrypto.decode_field(envelope[field])
        except (TypeError, ValueError) as exc:
            raise ManagedOAuthAuthError(
                "managed OAuth envelope has invalid %s" % field
            ) from exc
