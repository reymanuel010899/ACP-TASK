"""Small injectable AWS KMS interface used by managed OAuth custody.

``boto3`` is imported only when the production adapter is instantiated.
Tests and local development can inject a contract-compatible fake without
installing AWS libraries or possessing credentials.
"""

from dataclasses import dataclass
from typing import Optional


class KMSError(Exception):
    """Base error for KMS adapter failures."""


class KMSAccessDenied(KMSError):
    """The active AWS identity is not allowed to perform the operation."""


@dataclass(frozen=True)
class GeneratedDataKey:
    plaintext: Optional[bytes]
    ciphertext_blob: bytes
    key_id: str
    key_version: str


class AWSKMSClient(object):
    def __init__(self, client=None):
        if client is None:
            try:
                import boto3
            except ImportError as exc:
                raise KMSError(
                    "boto3 is required only for the production AWS KMS adapter"
                ) from exc
            client = boto3.client("kms")
        self.client = client

    def generate_data_key(self, key_id, encryption_context, caller_identity):
        try:
            response = self.client.generate_data_key(
                KeyId=key_id,
                KeySpec="AES_256",
                EncryptionContext=dict(encryption_context),
            )
        except Exception as exc:
            self._raise(exc)
        resolved_key_id = response.get("KeyId", key_id)
        return GeneratedDataKey(
            plaintext=bytes(response["Plaintext"]),
            ciphertext_blob=bytes(response["CiphertextBlob"]),
            key_id=resolved_key_id,
            key_version=resolved_key_id,
        )

    def decrypt_data_key(
        self, ciphertext_blob, key_id, encryption_context, caller_identity
    ):
        try:
            response = self.client.decrypt(
                CiphertextBlob=ciphertext_blob,
                KeyId=key_id,
                EncryptionContext=dict(encryption_context),
            )
            return bytes(response["Plaintext"])
        except Exception as exc:
            self._raise(exc)

    def rewrap_data_key(
        self,
        ciphertext_blob,
        source_key_id,
        destination_key_id,
        encryption_context,
        caller_identity,
    ):
        try:
            response = self.client.re_encrypt(
                CiphertextBlob=ciphertext_blob,
                SourceKeyId=source_key_id,
                DestinationKeyId=destination_key_id,
                SourceEncryptionContext=dict(encryption_context),
                DestinationEncryptionContext=dict(encryption_context),
            )
        except Exception as exc:
            self._raise(exc)
        resolved_key_id = response.get("KeyId", destination_key_id)
        return GeneratedDataKey(
            plaintext=None,
            ciphertext_blob=bytes(response["CiphertextBlob"]),
            key_id=resolved_key_id,
            key_version=resolved_key_id,
        )

    @staticmethod
    def _raise(exc):
        code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
        if code in ("AccessDenied", "AccessDeniedException"):
            raise KMSAccessDenied("AWS KMS access denied") from exc
        raise KMSError("AWS KMS operation failed") from exc
