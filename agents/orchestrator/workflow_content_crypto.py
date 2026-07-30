"""KMS-backed authenticated encryption for short-lived workflow content."""

import json

from vault.managed_oauth_crypto import ManagedOAuthCrypto


class WorkflowContentCrypto(object):
    def __init__(self, kms, key_id, service_identity):
        self.identity = service_identity
        self.crypto = ManagedOAuthCrypto(
            kms, key_id, ingestion_identities={service_identity},
            broker_identity=service_identity,
        )

    def seal(self, value, context):
        plaintext = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return self.crypto.seal(plaintext, context, self.identity)

    def open(self, envelope, context):
        plaintext = self.crypto.open(envelope, context, self.identity)
        return json.loads(plaintext.decode("utf-8"))
