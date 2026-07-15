"""Tests for the AgentTrust core vocabulary JSON Schemas (RFC-0001).

Test-first: these tests define the contract the six schema files in
``schemas/`` must satisfy. All schemas are JSON Schema draft-07.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"

SCHEMA_NAMES = [
    "capability",
    "evidence",
    "verification-result",
    "reputation-record",
    "principal",
    "session",
]

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

# 32-byte ed25519 public key, base64 (44 chars, one '=' pad).
PUBLIC_KEY_B64 = "hSDwCYkwp1R0i33ctD73Wg2/Og0mOBr066SpjqqbTmo="
# 64-byte ed25519 signature, base64 (88 chars, '==' pad).
SIGNATURE_B64 = ("A" * 86) + "=="

SHA256_HEX = "d2f4ab3f7e1c9a0b5d6e8f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c"


def load_schema(name):
    path = SCHEMA_DIR / f"{name}.schema.json"
    with open(path) as f:
        return json.load(f)


def validate(name, instance):
    Draft7Validator(load_schema(name)).validate(instance)


def assert_rejected(name, instance):
    with pytest.raises(ValidationError):
        validate(name, instance)


def valid_capability():
    return {
        "id": "terraform.generate",
        "version": "1.0.0",
        "description": "Generate Terraform HCL from a natural-language request.",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
    }


def valid_principal():
    return {
        "principal_id": "principal-3f9c",
        "public_key": PUBLIC_KEY_B64,
        "key_algorithm": "ed25519",
        "display_name": "infra-agent",
    }


def valid_session():
    return {
        "session_id": "sess-01H9XYZ",
        "principal_id": "principal-3f9c",
        "issued_at": "2026-07-14T10:00:00Z",
        "expires_at": "2026-07-14T11:00:00Z",
        "principal_signature": SIGNATURE_B64,
    }


def valid_evidence():
    return {
        "evidence_id": "evd-0001",
        "session_id": "sess-01H9XYZ",
        "capability_id": "terraform.generate",
        "schema_valid": True,
        "tests_passed": True,
        "artifact_hashes": {"main.tf": SHA256_HEX},
        "created_at": "2026-07-14T10:30:00Z",
    }


def valid_verification_result():
    return {
        "result_id": "vr-0001",
        "evidence_id": "evd-0001",
        "principal_id": "principal-verifier-77",
        "verdict": "verified",
        "reasoning": "Schema validated and all 12 acceptance tests passed.",
        "verified_at": "2026-07-14T10:35:00Z",
    }


def valid_reputation_record():
    return {
        "principal_id": "principal-3f9c",
        "capability_id": "terraform.generate",
        "tasks_verified": 9,
        "tasks_rejected": 1,
        "verification_rate": 0.9,
        "updated_at": "2026-07-14T10:40:00Z",
    }


# ---------------------------------------------------------------------------
# Schema sanity: files exist, are valid draft-07, carry the right $id
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_schema_file_is_valid_draft07(name):
    schema = load_schema(name)
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
    Draft7Validator.check_schema(schema)


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_schema_has_expected_id(name):
    schema = load_schema(name)
    assert schema["$id"] == f"https://agenttrust.example/schemas/{name}.schema.json"


# ---------------------------------------------------------------------------
# Happy path: valid instances validate
# ---------------------------------------------------------------------------


def test_valid_capability():
    validate("capability", valid_capability())


def test_valid_capability_minimal():
    validate(
        "capability",
        {
            "id": "code.review",
            "version": "0.1.0",
            "description": "Review a diff and report findings.",
        },
    )


def test_valid_principal():
    validate("principal", valid_principal())


def test_valid_session():
    validate("session", valid_session())


def test_valid_evidence():
    validate("evidence", valid_evidence())


def test_valid_evidence_failed_task_still_wellformed():
    # Evidence of a failed run is still valid Evidence.
    ev = valid_evidence()
    ev["schema_valid"] = False
    ev["tests_passed"] = False
    validate("evidence", ev)


def test_valid_verification_result_verified():
    validate("verification-result", valid_verification_result())


def test_valid_verification_result_rejected():
    vr = valid_verification_result()
    vr["verdict"] = "rejected"
    vr["reasoning"] = "Artifact hash mismatch against submitted output."
    validate("verification-result", vr)


def test_valid_reputation_record():
    validate("reputation-record", valid_reputation_record())


# ---------------------------------------------------------------------------
# Edge case: neutral reputation for a principal with zero completed tasks
# ---------------------------------------------------------------------------


def test_reputation_neutral_state_validates():
    """Zero tasks => counts 0 and verification_rate null (neutral, not 0.0).

    The neutral state must be representable so a new principal is not
    'failed by default'.
    """
    validate(
        "reputation-record",
        {
            "principal_id": "principal-new",
            "capability_id": "terraform.generate",
            "tasks_verified": 0,
            "tasks_rejected": 0,
            "verification_rate": None,
            "updated_at": "2026-07-14T10:40:00Z",
        },
    )


def test_reputation_rate_out_of_bounds_rejected():
    rec = valid_reputation_record()
    rec["verification_rate"] = 1.5
    assert_rejected("reputation-record", rec)


def test_reputation_negative_count_rejected():
    rec = valid_reputation_record()
    rec["tasks_rejected"] = -1
    assert_rejected("reputation-record", rec)


# ---------------------------------------------------------------------------
# Edge case: Evidence missing the required hash field is rejected
# ---------------------------------------------------------------------------


def test_evidence_missing_artifact_hashes_rejected():
    ev = valid_evidence()
    del ev["artifact_hashes"]
    assert_rejected("evidence", ev)


def test_evidence_malformed_hash_rejected():
    ev = valid_evidence()
    ev["artifact_hashes"] = {"main.tf": "not-a-sha256"}
    assert_rejected("evidence", ev)


def test_evidence_missing_session_link_rejected():
    ev = valid_evidence()
    del ev["session_id"]
    assert_rejected("evidence", ev)


# ---------------------------------------------------------------------------
# Error path: Session without the signed Principal link fails validation
# ---------------------------------------------------------------------------


def test_session_without_signature_rejected():
    sess = valid_session()
    del sess["principal_signature"]
    assert_rejected("session", sess)


def test_session_without_principal_id_rejected():
    sess = valid_session()
    del sess["principal_id"]
    assert_rejected("session", sess)


def test_session_malformed_signature_rejected():
    sess = valid_session()
    sess["principal_signature"] = "definitely not base64!!!"
    assert_rejected("session", sess)


# ---------------------------------------------------------------------------
# Other rejection cases
# ---------------------------------------------------------------------------


def test_principal_missing_public_key_rejected():
    p = valid_principal()
    del p["public_key"]
    assert_rejected("principal", p)


def test_principal_malformed_public_key_rejected():
    p = valid_principal()
    p["public_key"] = "short"
    assert_rejected("principal", p)


def test_capability_missing_id_rejected():
    cap = valid_capability()
    del cap["id"]
    assert_rejected("capability", cap)


def test_verification_result_bad_verdict_rejected():
    vr = valid_verification_result()
    vr["verdict"] = "maybe"
    assert_rejected("verification-result", vr)


def test_verification_result_missing_reasoning_rejected():
    vr = valid_verification_result()
    del vr["reasoning"]
    assert_rejected("verification-result", vr)


def test_unknown_top_level_property_rejected():
    # additionalProperties is false: unknown fields must be rejected so
    # extensions go through the explicit `extensions` bag instead.
    ev = valid_evidence()
    ev["totally_unknown_field"] = 1
    assert_rejected("evidence", ev)


def test_extensions_bag_allowed():
    ev = valid_evidence()
    ev["extensions"] = {"vendor.example/trace_id": "abc123"}
    validate("evidence", ev)
