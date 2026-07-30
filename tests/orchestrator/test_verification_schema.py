"""Receipt-based and mixed Evidence schema coverage (U10)."""

import json
from pathlib import Path

import jsonschema

from agents.orchestrator.attestation import ExecutionAttestor
from libs.signing import generate_keypair


SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[2] / "schemas" / "evidence.schema.json"
    ).read_text()
)


def _execution_attestation():
    key = generate_keypair()
    return ExecutionAttestor(
        "broker-key-1", key.signing_key, clock=lambda: 1_700_000_000
    ).create(
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
        },
        idempotency_key="action-1",
        outcome="succeeded",
        approved_payload={"event": {"summary": "Interview"}},
    )


def test_schema_accepts_attestation_only_and_mixed_artifact_evidence():
    attestation = _execution_attestation()
    receipt_only = {
        "evidence_id": attestation["attestation_id"],
        "capability_id": "calendar.create",
        "execution_attestation": attestation,
    }
    jsonschema.validate(receipt_only, SCHEMA)

    mixed = dict(
        receipt_only,
        session_id="session-1",
        schema_valid=True,
        tests_passed=True,
        artifact_hashes={"summary.txt": "b" * 64},
    )
    jsonschema.validate(mixed, SCHEMA)


def test_schema_keeps_legacy_artifact_evidence_compatible():
    jsonschema.validate(
        {
            "evidence_id": "evidence-legacy",
            "session_id": "session-1",
            "capability_id": "terraform.generate",
            "schema_valid": True,
            "tests_passed": True,
            "artifact_hashes": {"main.tf": "c" * 64},
        },
        SCHEMA,
    )


def test_schema_rejects_unknown_or_partial_attestation_shapes():
    attestation = _execution_attestation()
    invalid = {
        "evidence_id": attestation["attestation_id"],
        "capability_id": "calendar.create",
        "execution_attestation": dict(attestation, surprise="not-authoritative"),
    }
    try:
        jsonschema.validate(invalid, SCHEMA)
    except jsonschema.ValidationError:
        pass
    else:
        raise AssertionError("unknown attestation field was accepted")
