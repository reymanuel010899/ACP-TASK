"""Tests for the AgentTrust Verification & Reputation Service (unit U3).

Test-first: the core accept/reject tests below define the contract of
``services.verification.app`` before the implementation exists. The service
is exercised via direct function/class calls (no HTTP); the HTTP layer is
covered separately at the end with a threaded stdlib server.

Canonical session signing form (decision, see app.py docstring): the ed25519
signature is computed over the UTF-8 bytes of the JSON serialization, with
sorted keys and no whitespace, of exactly::

    {"expires_at": ..., "principal_id": ..., "session_id": ...}
"""

import base64
import hashlib
import json
import uuid
from pathlib import Path

import pytest
from jsonschema import Draft7Validator
from nacl.signing import SigningKey

from services.verification.app import (
    VerificationService,
    canonical_session_claims,
    validate_terraform_syntax,
)
from services.verification.reputation_store import ReputationStore

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"

CAPABILITY_ID = "terraform.generate"

VALID_HCL = """
resource "aws_s3_bucket" "demo" {
  bucket = "agenttrust-demo"
  tags = {
    Name = "demo"
  }
}
"""

# Schema-valid evidence can still carry this: unbalanced braces.
INVALID_HCL = """
resource "aws_s3_bucket" "demo" {
  bucket = "agenttrust-demo"
"""


def load_schema(name):
    with open(SCHEMA_DIR / ("%s.schema.json" % name)) as f:
        return json.load(f)


def assert_valid(name, instance):
    Draft7Validator(load_schema(name)).validate(instance)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def make_identity(principal_id="agent:alice"):
    """Return (signing_key, principal_dict)."""
    sk = SigningKey.generate()
    public_key = base64.b64encode(bytes(sk.verify_key)).decode("ascii")
    principal = {
        "principal_id": principal_id,
        "public_key": public_key,
        "key_algorithm": "ed25519",
    }
    return sk, principal


def sign_claims(sk, claims):
    message = json.dumps(claims, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return base64.b64encode(sk.sign(message).signature).decode("ascii")


def make_session(sk, principal_id, expires_at="2099-01-01T00:00:00Z"):
    session_id = "sess-%s" % uuid.uuid4().hex
    claims = {
        "session_id": session_id,
        "principal_id": principal_id,
        "expires_at": expires_at,
    }
    return {
        "session_id": session_id,
        "principal_id": principal_id,
        "issued_at": "2026-07-14T10:00:00Z",
        "expires_at": expires_at,
        "principal_signature": sign_claims(sk, claims),
    }


def make_evidence(session, hcl=VALID_HCL, capability_id=CAPABILITY_ID, **over):
    evidence = {
        "evidence_id": "ev-%s" % uuid.uuid4().hex,
        "session_id": session["session_id"],
        "capability_id": capability_id,
        "schema_valid": True,
        "tests_passed": True,
        "artifact_hashes": {
            "main.tf": hashlib.sha256(hcl.encode("utf-8")).hexdigest()
        },
        "created_at": "2026-07-14T10:05:00Z",
        "extensions": {"terraform_hcl": hcl},
    }
    evidence.update(over)
    return evidence


def make_submission(hcl=VALID_HCL, principal_id="agent:alice", **evidence_over):
    sk, principal = make_identity(principal_id)
    session = make_session(sk, principal_id)
    evidence = make_evidence(session, hcl=hcl, **evidence_over)
    return sk, {"evidence": evidence, "session": session, "principal": principal}


@pytest.fixture
def store():
    return ReputationStore()


@pytest.fixture
def service(store):
    return VerificationService(store)


# ---------------------------------------------------------------------------
# Core accept/reject pipeline (direct calls, no HTTP)
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_valid_evidence_is_verified(self, service, store):
        _, payload = make_submission()
        status, body = service.process_evidence(payload)

        assert status == 200
        result = body["verification_result"]
        assert result["verdict"] == "verified"
        assert result["evidence_id"] == payload["evidence"]["evidence_id"]
        # The result names the *verifier* principal, not the subject.
        assert result["principal_id"] == service.verifier_principal_id
        assert_valid("verification-result", result)

        # Result is retrievable from the store.
        stored = store.get_result(payload["evidence"]["evidence_id"])
        assert stored == result

    def test_verified_increments_reputation(self, service, store):
        _, payload = make_submission()
        status, body = service.process_evidence(payload)

        assert status == 200
        record = body["reputation_record"]
        assert record["principal_id"] == "agent:alice"
        assert record["capability_id"] == CAPABILITY_ID
        assert record["tasks_verified"] == 1
        assert record["tasks_rejected"] == 0
        assert record["verification_rate"] == 1.0
        assert_valid("reputation-record", record)

        records = store.get_reputation("agent:alice")
        assert len(records) == 1
        assert records[0] == record


class TestTaskSpecificRejection:
    def test_invalid_terraform_is_rejected_not_verified(self, service, store):
        _, payload = make_submission(hcl=INVALID_HCL)
        status, body = service.process_evidence(payload)

        assert status == 200
        result = body["verification_result"]
        assert result["verdict"] == "rejected"
        assert_valid("verification-result", result)

        record = body["reputation_record"]
        assert record["tasks_verified"] == 0
        assert record["tasks_rejected"] == 1
        assert record["verification_rate"] == 0.0
        assert_valid("reputation-record", record)

    def test_missing_terraform_extension_is_rejected(self, service):
        _, payload = make_submission()
        payload["evidence"]["extensions"] = {}
        status, body = service.process_evidence(payload)

        assert status == 200
        assert body["verification_result"]["verdict"] == "rejected"

    def test_failed_task_booleans_are_rejected(self, service):
        _, payload = make_submission(tests_passed=False)
        status, body = service.process_evidence(payload)

        assert status == 200
        assert body["verification_result"]["verdict"] == "rejected"


class TestSessionLinkErrors:
    def test_bad_signature_rejected_without_reputation_write(self, service, store):
        _, payload = make_submission()
        # Signature by a *different* key: syntactically fine, cryptographically wrong.
        other_sk, _ = make_identity("agent:mallory")
        payload["session"]["principal_signature"] = sign_claims(
            other_sk,
            {
                "session_id": payload["session"]["session_id"],
                "principal_id": payload["session"]["principal_id"],
                "expires_at": payload["session"]["expires_at"],
            },
        )

        status, body = service.process_evidence(payload)

        assert status == 422
        assert "verification_result" not in body
        assert store.get_reputation("agent:alice") == []
        assert store.get_result(payload["evidence"]["evidence_id"]) is None

    def test_missing_signature_rejected(self, service, store):
        _, payload = make_submission()
        del payload["session"]["principal_signature"]

        status, body = service.process_evidence(payload)

        assert status == 422
        assert store.get_reputation("agent:alice") == []

    def test_expired_session_rejected(self, service, store):
        sk, principal = make_identity()
        session = make_session(
            sk, principal["principal_id"], expires_at="2000-01-01T00:00:00Z"
        )
        payload = {
            "evidence": make_evidence(session),
            "session": session,
            "principal": principal,
        }

        status, body = service.process_evidence(payload)

        assert status == 422
        assert store.get_reputation("agent:alice") == []

    def test_session_evidence_mismatch_rejected(self, service, store):
        _, payload = make_submission()
        payload["evidence"]["session_id"] = "sess-someone-else"

        status, body = service.process_evidence(payload)

        assert status == 422
        assert store.get_reputation("agent:alice") == []


class TestEvidenceSchemaErrors:
    def test_schema_invalid_evidence_rejected_without_write(self, service, store):
        _, payload = make_submission()
        del payload["evidence"]["artifact_hashes"]

        status, body = service.process_evidence(payload)

        assert status == 422
        assert store.get_reputation("agent:alice") == []

    def test_unknown_top_level_field_rejected(self, service, store):
        _, payload = make_submission()
        payload["evidence"]["bogus_field"] = 1

        status, body = service.process_evidence(payload)

        assert status == 422
        assert store.get_reputation("agent:alice") == []


class TestRevocation:
    def test_revoked_public_key_rejected_despite_valid_everything(
        self, service, store
    ):
        _, payload = make_submission()
        store.revoke(payload["principal"]["public_key"])

        status, body = service.process_evidence(payload)

        assert status == 403
        result = body["verification_result"]
        assert result["verdict"] == "rejected"
        assert "revoked key" in result["reasoning"]
        assert_valid("verification-result", result)
        # No reputation write of any kind.
        assert store.get_reputation("agent:alice") == []

    def test_revoked_principal_id_rejected(self, service, store):
        _, payload = make_submission()
        store.revoke(payload["principal"]["principal_id"])

        status, body = service.process_evidence(payload)

        assert status == 403
        assert body["verification_result"]["verdict"] == "rejected"
        assert store.get_reputation("agent:alice") == []


class TestAccumulation:
    def test_two_verified_tasks_accumulate(self, store):
        service = VerificationService(store)
        sk, principal = make_identity("agent:bob")

        for _ in range(2):
            session = make_session(sk, "agent:bob")
            payload = {
                "evidence": make_evidence(session),
                "session": session,
                "principal": principal,
            }
            status, body = service.process_evidence(payload)
            assert status == 200
            assert body["verification_result"]["verdict"] == "verified"

        records = store.get_reputation("agent:bob", capability_id=CAPABILITY_ID)
        assert len(records) == 1
        record = records[0]
        assert record["tasks_verified"] == 2
        assert record["tasks_rejected"] == 0
        assert record["verification_rate"] == 1.0
        assert_valid("reputation-record", record)

    def test_mixed_verdicts_accumulate(self, store):
        service = VerificationService(store)
        sk, principal = make_identity("agent:carol")

        for hcl in (VALID_HCL, INVALID_HCL):
            session = make_session(sk, "agent:carol")
            payload = {
                "evidence": make_evidence(session, hcl=hcl),
                "session": session,
                "principal": principal,
            }
            status, _ = service.process_evidence(payload)
            assert status == 200

        (record,) = store.get_reputation("agent:carol")
        assert record["tasks_verified"] == 1
        assert record["tasks_rejected"] == 1
        assert record["verification_rate"] == 0.5


# ---------------------------------------------------------------------------
# Terraform syntax checker
# ---------------------------------------------------------------------------


class TestValidateTerraformSyntax:
    def test_valid_hcl(self):
        ok, reason = validate_terraform_syntax(VALID_HCL)
        assert ok, reason

    def test_unbalanced_braces(self):
        ok, reason = validate_terraform_syntax(INVALID_HCL)
        assert not ok
        assert reason

    def test_empty_text(self):
        ok, _ = validate_terraform_syntax("")
        assert not ok

    def test_no_resource_block(self):
        ok, _ = validate_terraform_syntax('variable "x" {\n  default = 1\n}\n')
        assert not ok

    def test_unbalanced_quotes(self):
        ok, _ = validate_terraform_syntax(
            'resource "aws_s3_bucket" "b" {\n  bucket = "oops\n}\n'
        )
        assert not ok

    def test_braces_inside_strings_ignored(self):
        ok, reason = validate_terraform_syntax(
            'resource "aws_s3_bucket" "b" {\n  bucket = "brace-{-in-string"\n}\n'
        )
        assert ok, reason

    def test_non_string_input(self):
        ok, _ = validate_terraform_syntax(None)
        assert not ok


# ---------------------------------------------------------------------------
# Canonical claims form
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# HTTP layer end-to-end (threaded stdlib server on an OS-assigned port)
# ---------------------------------------------------------------------------


@pytest.fixture
def http_service():
    import threading

    import requests

    from services.verification.app import make_server

    store = ReputationStore()
    server = make_server(port=0, store=store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = "http://%s:%d" % server.server_address[:2]
    try:
        yield requests, base_url, store
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class TestHTTPEndToEnd:
    def test_post_evidence_then_get_reputation(self, http_service):
        requests, base_url, _ = http_service

        health = requests.get(base_url + "/healthz", timeout=5)
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        _, payload = make_submission()
        resp = requests.post(base_url + "/evidence", json=payload, timeout=5)
        assert resp.status_code == 200
        body = resp.json()
        assert body["verification_result"]["verdict"] == "verified"
        assert_valid("verification-result", body["verification_result"])
        assert_valid("reputation-record", body["reputation_record"])

        rep = requests.get(base_url + "/reputation/agent:alice", timeout=5)
        assert rep.status_code == 200
        records = rep.json()["reputation_records"]
        assert len(records) == 1
        assert records[0]["capability_id"] == CAPABILITY_ID
        assert records[0]["tasks_verified"] == 1
        assert records[0]["verification_rate"] == 1.0

        # Capability filter: matching and non-matching.
        rep = requests.get(
            base_url + "/reputation/agent:alice",
            params={"capability_id": CAPABILITY_ID},
            timeout=5,
        )
        assert len(rep.json()["reputation_records"]) == 1
        rep = requests.get(
            base_url + "/reputation/agent:alice",
            params={"capability_id": "other.capability"},
            timeout=5,
        )
        assert rep.json()["reputation_records"] == []

        # The Verification Result is retrievable by evidence_id.
        vr = requests.get(
            base_url
            + "/verification-results/"
            + payload["evidence"]["evidence_id"],
            timeout=5,
        )
        assert vr.status_code == 200
        assert vr.json()["verification_result"]["verdict"] == "verified"

        missing = requests.get(
            base_url + "/verification-results/ev-nope", timeout=5
        )
        assert missing.status_code == 404

        # Portfolio (U3): the verified work shows for the subject principal.
        portfolio = requests.get(
            base_url + "/portfolio/agent:alice",
            params={"capability_id": CAPABILITY_ID},
            timeout=5,
        )
        assert portfolio.status_code == 200
        entries = portfolio.json()["portfolio"]
        assert len(entries) == 1
        assert entries[0]["evidence_id"] == payload["evidence"]["evidence_id"]
        assert entries[0]["verdict"] == "verified"

        # Empty (not 404) for a principal with no history.
        empty = requests.get(base_url + "/portfolio/agent:nobody", timeout=5)
        assert empty.status_code == 200
        assert empty.json()["portfolio"] == []

    def test_post_revocation_then_evidence_403(self, http_service):
        requests, base_url, _ = http_service
        _, payload = make_submission(principal_id="agent:dave")

        revoke = requests.post(
            base_url + "/revocations",
            json={"public_key": payload["principal"]["public_key"]},
            timeout=5,
        )
        assert revoke.status_code == 200

        resp = requests.post(base_url + "/evidence", json=payload, timeout=5)
        assert resp.status_code == 403
        assert resp.json()["verification_result"]["verdict"] == "rejected"
        assert "revoked key" in resp.json()["verification_result"]["reasoning"]

        rep = requests.get(base_url + "/reputation/agent:dave", timeout=5)
        assert rep.json()["reputation_records"] == []

    def test_invalid_json_body_is_400(self, http_service):
        requests, base_url, _ = http_service
        resp = requests.post(
            base_url + "/evidence",
            data="not json",
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Store persistence and revocation file loading
# ---------------------------------------------------------------------------


class TestStorePersistence:
    def test_round_trip_via_json_file(self, tmp_path):
        store_path = str(tmp_path / "store.json")
        store = ReputationStore(path=store_path)
        service = VerificationService(store)
        _, payload = make_submission(principal_id="agent:eve")
        status, _ = service.process_evidence(payload)
        assert status == 200

        reloaded = ReputationStore(path=store_path)
        (record,) = reloaded.get_reputation("agent:eve")
        assert record["tasks_verified"] == 1
        assert (
            reloaded.get_result(payload["evidence"]["evidence_id"])["verdict"]
            == "verified"
        )

    def test_revocation_list_loaded_from_file(self, tmp_path):
        rev_path = tmp_path / "revoked.json"
        rev_path.write_text(json.dumps(["agent:mallory"]))
        store = ReputationStore(revocation_path=str(rev_path))
        assert store.is_revoked("agent:mallory")
        assert not store.is_revoked("agent:alice")

        store.revoke("agent:trent")
        assert set(json.loads(rev_path.read_text())) == {
            "agent:mallory",
            "agent:trent",
        }


def test_canonical_session_claims_is_sorted_compact_json():
    session = {
        "session_id": "s1",
        "principal_id": "p1",
        "issued_at": "2026-07-14T10:00:00Z",
        "expires_at": "2099-01-01T00:00:00Z",
        "principal_signature": "x",
    }
    assert canonical_session_claims(session) == (
        b'{"expires_at":"2099-01-01T00:00:00Z",'
        b'"principal_id":"p1","session_id":"s1"}'
    )


# ---------------------------------------------------------------------------
# U3: verified-work portfolio
# ---------------------------------------------------------------------------


class TestPortfolio:
    def test_verified_work_enters_the_portfolio(self, service, store):
        _, payload = make_submission(principal_id="agent:alice")
        service.process_evidence(payload)
        entries = store.get_portfolio("agent:alice", capability_id=CAPABILITY_ID)
        assert len(entries) == 1
        assert entries[0]["verdict"] == "verified"
        assert entries[0]["evidence_id"] == payload["evidence"]["evidence_id"]

    def test_rejected_work_never_enters_the_portfolio(self, service, store):
        _, payload = make_submission(principal_id="agent:bob", hcl=INVALID_HCL)
        status, body = service.process_evidence(payload)
        assert body["verification_result"]["verdict"] == "rejected"
        assert store.get_portfolio("agent:bob") == []

    def test_portfolio_empty_for_principal_with_no_history(self, store):
        # Empty, never an error/None.
        assert store.get_portfolio("agent:nobody") == []
        assert store.get_portfolio("agent:nobody", capability_id="x.y") == []

    def test_portfolio_capability_filter_isolates(self, service, store):
        _, p = make_submission(principal_id="agent:carol")
        service.process_evidence(p)
        assert len(store.get_portfolio("agent:carol", capability_id=CAPABILITY_ID)) == 1
        assert store.get_portfolio("agent:carol", capability_id="other.cap") == []

    def test_get_portfolio_orders_newest_first_and_limits(self, store):
        # Craft entries directly so we control verified_at ordering.
        for i, ts in enumerate(
            ["2026-07-10T00:00:00Z", "2026-07-12T00:00:00Z", "2026-07-11T00:00:00Z"]
        ):
            store.add_portfolio_entry(
                "agent:dave",
                CAPABILITY_ID,
                {"evidence_id": "ev-%d" % i, "verdict": "verified", "verified_at": ts},
            )
        newest_two = store.get_portfolio("agent:dave", limit=2)
        assert [e["evidence_id"] for e in newest_two] == ["ev-1", "ev-2"]

    def test_add_portfolio_entry_ignores_rejected(self, store):
        store.add_portfolio_entry(
            "agent:eve",
            CAPABILITY_ID,
            {"evidence_id": "ev-x", "verdict": "rejected", "verified_at": "z"},
        )
        assert store.get_portfolio("agent:eve") == []
