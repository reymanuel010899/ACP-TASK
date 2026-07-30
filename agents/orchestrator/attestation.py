"""Broker-authored, Ed25519-signed execution attestations."""

import base64
import binascii
import hashlib
import json
import time

import nacl.exceptions
import nacl.signing

from libs.signing import public_key_b64


_REQUIRED_FIELDS = (
    "attestation_id",
    "task_id",
    "user_principal_id",
    "agent_principal_id",
    "credential_id",
    "capability_id",
    "approved_payload_hash",
    "provider_receipt",
    "idempotency_key",
    "executed_at",
    "outcome",
    "broker_key_id",
    "material_hashes",
    "signature",
)
_RECEIPT_FIELDS = (
    "provider",
    "capability_id",
    "provider_id",
    "provider_account_hash",
    "provider_timestamp",
    "team_id",
    "channel_id",
    "message_ts",
    "file_id",
    "reaction",
)


class AttestationError(ValueError):
    """An execution attestation is malformed, unknown, or has a bad signature."""


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def _canonical_bytes(attestation):
    signed = {
        key: attestation[key]
        for key in _REQUIRED_FIELDS
        if key != "signature"
    }
    return _canonical(signed).encode("utf-8")


def _hash(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def material_projection(capability_id, payload):
    """Return the minimum capability-specific material needed for checking."""
    payload = payload if isinstance(payload, dict) else {}
    if capability_id == "calendar.create":
        event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
        projection = {
            key: event[key]
            for key in ("summary", "start", "end")
            if key in event
        }
        attendees = event.get("attendees")
        if isinstance(attendees, list):
            projection["attendees"] = sorted(
                item.get("email")
                for item in attendees
                if isinstance(item, dict)
                and isinstance(item.get("email"), str)
            )
        return projection
    if capability_id == "gmail.send":
        return {"raw": payload["raw"]} if "raw" in payload else {}
    if capability_id == "drive.upload":
        return {
            key: payload[key]
            for key in ("name", "mime_type")
            if key in payload
        }
    if capability_id in ("slack.message.send", "slack.thread.reply"):
        return {
            key: payload[key]
            for key in ("channel_id", "thread_ts", "text")
            if key in payload
        }
    if capability_id == "slack.reaction.add":
        return {
            key: payload[key]
            for key in ("channel_id", "message_ts", "reaction")
            if key in payload
        }
    if capability_id == "slack.file.upload":
        return {
            key: payload[key]
            for key in ("channel_id", "filename", "content_hash")
            if key in payload
        }
    return {}


def material_hashes(capability_id, payload):
    return {
        key: _hash(value)
        for key, value in material_projection(capability_id, payload).items()
    }


def _filtered_receipt(receipt):
    if not isinstance(receipt, dict):
        raise AttestationError("provider receipt must be an object")
    filtered = {
        key: receipt[key]
        for key in _RECEIPT_FIELDS
        if key in receipt
    }
    for field in ("provider", "capability_id", "provider_id"):
        if not isinstance(filtered.get(field), str) or not filtered[field]:
            raise AttestationError("provider receipt is missing %s" % field)
    return filtered


class ExecutionAttestor(object):
    """Issue broker-authoritative attestations with one configured key."""

    def __init__(self, broker_key_id, signing_key, clock=None):
        if not isinstance(broker_key_id, str) or not broker_key_id:
            raise ValueError("broker_key_id is required")
        if hasattr(signing_key, "signing_key"):
            signing_key = signing_key.signing_key
        if not isinstance(signing_key, nacl.signing.SigningKey):
            raise ValueError("an Ed25519 signing key is required")
        self.broker_key_id = broker_key_id
        self.signing_key = signing_key
        self.clock = clock or time.time

    @property
    def public_key(self):
        return public_key_b64(self.signing_key.verify_key)

    def create(
        self,
        task_id,
        user_principal_id,
        agent_principal_id,
        credential_id,
        capability_id,
        approved_payload_hash,
        provider_receipt,
        idempotency_key,
        outcome,
        approved_payload=None,
        executed_at=None,
    ):
        values = (
            task_id,
            user_principal_id,
            agent_principal_id,
            credential_id,
            capability_id,
            approved_payload_hash,
            idempotency_key,
            outcome,
        )
        if any(not isinstance(value, str) or not value for value in values):
            raise AttestationError("all execution binding fields are required")
        if (
            len(approved_payload_hash) != 64
            or any(char not in "0123456789abcdef" for char in approved_payload_hash)
        ):
            raise AttestationError("approved payload hash must be sha256")
        receipt = _filtered_receipt(provider_receipt)
        if receipt["capability_id"] != capability_id:
            raise AttestationError("receipt capability does not match execution")
        executed_at = int(self.clock() if executed_at is None else executed_at)
        identity = _hash(
            {
                "idempotency_key": idempotency_key,
                "provider_receipt": receipt,
            }
        )
        attestation = {
            "attestation_id": "attestation-%s" % identity,
            "task_id": task_id,
            "user_principal_id": user_principal_id,
            "agent_principal_id": agent_principal_id,
            "credential_id": credential_id,
            "capability_id": capability_id,
            "approved_payload_hash": approved_payload_hash,
            "provider_receipt": receipt,
            "idempotency_key": idempotency_key,
            "executed_at": executed_at,
            "outcome": outcome,
            "broker_key_id": self.broker_key_id,
            "material_hashes": material_hashes(
                capability_id, approved_payload or {}
            ),
        }
        attestation["signature"] = base64.b64encode(
            self.signing_key.sign(_canonical_bytes(attestation)).signature
        ).decode("ascii")
        return attestation


def verify_execution_attestation(attestation, broker_keys):
    """Verify structure, known broker key identity, and detached signature."""
    if not isinstance(attestation, dict) or set(attestation) != set(
        _REQUIRED_FIELDS
    ):
        raise AttestationError("execution attestation shape is invalid")
    key_id = attestation.get("broker_key_id")
    if callable(broker_keys):
        public_key = broker_keys(key_id)
    elif isinstance(broker_keys, dict):
        public_key = broker_keys.get(key_id)
    else:
        public_key = None
    if not isinstance(public_key, str) or not public_key:
        raise AttestationError("broker signing key is unknown")
    _filtered_receipt(attestation.get("provider_receipt"))
    if not isinstance(attestation.get("material_hashes"), dict):
        raise AttestationError("material_hashes must be an object")
    try:
        verify_key = nacl.signing.VerifyKey(base64.b64decode(public_key))
        signature = base64.b64decode(
            attestation["signature"], validate=True
        )
        verify_key.verify(_canonical_bytes(attestation), signature)
    except (
        binascii.Error,
        ValueError,
        TypeError,
        nacl.exceptions.BadSignatureError,
    ) as exc:
        raise AttestationError("execution attestation signature is invalid") from exc
    return True
