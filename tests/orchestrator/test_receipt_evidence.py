"""Broker-authored execution attestation coverage (U10)."""

import json

import pytest

from agents.orchestrator.attestation import (
    AttestationError,
    ExecutionAttestor,
    verify_execution_attestation,
)
from libs.signing import generate_keypair


NOW = 1_700_000_000


def _attestor():
    keypair = generate_keypair()
    return (
        ExecutionAttestor(
            "broker-key-1", keypair.signing_key, clock=lambda: NOW
        ),
        {"broker-key-1": keypair.public_key_b64()},
    )


def _attestation(attestor):
    return attestor.create(
        task_id="task-1",
        user_principal_id="user:alice",
        agent_principal_id="agent:calendar",
        credential_id="credential:google",
        capability_id="calendar.create",
        approved_payload_hash="a" * 64,
        provider_receipt={
            "provider": "google",
            "capability_id": "calendar.create",
            "provider_id": "event-7",
            "attendees": ["private@example.test"],
        },
        idempotency_key="action-1",
        outcome="succeeded",
        approved_payload={
            "event": {
                "summary": "Interview",
                "attendees": [{"email": "private@example.test"}],
            }
        },
    )


def test_broker_attestation_serializes_and_verifies_without_sensitive_fields():
    attestor, broker_keys = _attestor()
    attestation = _attestation(attestor)

    assert verify_execution_attestation(attestation, broker_keys) is True
    assert json.loads(json.dumps(attestation)) == attestation
    serialized = json.dumps(attestation)
    assert "private@example.test" not in serialized
    assert attestation["provider_receipt"] == {
        "provider": "google",
        "capability_id": "calendar.create",
        "provider_id": "event-7",
    }
    assert attestation["material_hashes"]["attendees"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_id", "task-other"),
        ("approved_payload_hash", "b" * 64),
        ("executed_at", NOW + 1),
    ],
)
def test_tampered_bound_field_fails_signature(field, value):
    attestor, broker_keys = _attestor()
    attestation = _attestation(attestor)
    attestation[field] = value

    with pytest.raises(AttestationError):
        verify_execution_attestation(attestation, broker_keys)


def test_tampered_receipt_or_signature_fails():
    attestor, broker_keys = _attestor()
    receipt_tampered = _attestation(attestor)
    receipt_tampered["provider_receipt"]["provider_id"] = "event-other"
    with pytest.raises(AttestationError):
        verify_execution_attestation(receipt_tampered, broker_keys)

    signature_tampered = _attestation(attestor)
    signature_tampered["signature"] = "not-a-signature"
    with pytest.raises(AttestationError):
        verify_execution_attestation(signature_tampered, broker_keys)
