"""Cross-service reputation unification (unit U5, R2).

Before U5, ``registry/user_index.py`` and
``services/verification/reputation_store.py`` each kept an independent,
unsynchronized in-memory reputation copy; the ONLY way a test could show
"the same reputation view from both services" was to inject the SAME
Python ``ReputationStore`` object into both a ``RegistryService`` and a
``VerificationService`` (see ``tests/registry/test_capability_search.py``'s
``TestVerificationServiceIntegration``, which the plan explicitly keeps for
its own, narrower "shared in-process object" scenario).

This test proves the REAL consolidation instead: two independent instances
-- one ``RegistryService`` (via ``registry/user_index.py``, backed by
``libs.reputation_repository.ReputationRepository``), one
``VerificationService`` (via ``services/verification/reputation_store.py``,
backed by the SAME repository class) -- that share NO Python object at all,
only a Postgres ``DATABASE_URL``. A verdict recorded through one is visible
through the other's own read path on the very next call, with no manual
sync step.
"""

import base64
import hashlib
import json
import uuid

import pytest
from nacl.signing import SigningKey

from registry.app import RegistryService
from registry.index_store import IndexStore
from registry.user_index import UserIndex
from services.verification.app import VerificationService
from services.verification.reputation_store import ReputationStore

CAPABILITY_ID = "terraform.generate"

VALID_HCL = """
resource "aws_s3_bucket" "demo" {
  bucket = "agenttrust-demo"
}
"""


def _make_submission(principal_id):
    sk = SigningKey.generate()
    public_key = base64.b64encode(bytes(sk.verify_key)).decode("ascii")
    principal = {
        "principal_id": principal_id,
        "public_key": public_key,
        "key_algorithm": "ed25519",
    }
    session_id = "sess-%s" % uuid.uuid4().hex
    claims = {
        "session_id": session_id,
        "principal_id": principal_id,
        "expires_at": "2099-01-01T00:00:00Z",
    }
    signature = base64.b64encode(
        sk.sign(
            json.dumps(claims, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).signature
    ).decode("ascii")
    session = {
        "session_id": session_id,
        "principal_id": principal_id,
        "issued_at": "2026-07-14T10:00:00Z",
        "expires_at": "2099-01-01T00:00:00Z",
        "principal_signature": signature,
    }
    evidence = {
        "evidence_id": "ev-%s" % uuid.uuid4().hex,
        "session_id": session_id,
        "capability_id": CAPABILITY_ID,
        "schema_valid": True,
        "tests_passed": True,
        "artifact_hashes": {
            "main.tf": hashlib.sha256(VALID_HCL.encode("utf-8")).hexdigest()
        },
        "created_at": "2026-07-14T10:05:00Z",
        "extensions": {"terraform_hcl": VALID_HCL},
    }
    return {"evidence": evidence, "session": session, "principal": principal}


class TestCrossServiceReputationUnification:
    def test_verification_write_visible_via_registry_user_endpoint(self):
        """A verdict recorded via an independent VerificationService
        instance (its own ReputationStore/ReputationRepository, no shared
        Python object) is immediately visible via RegistryService's OWN
        user_index read path (also backed by ReputationRepository) --
        proving R2's single canonical trust.reputation_records table, not
        two federated copies."""
        principal_id = "agent:unification-%s" % uuid.uuid4().hex[:8]

        # Registry service: register the agent as a user Principal (its own
        # UserIndex/IdentityRepository, no reputation_store injected at all).
        registry_service = RegistryService(IndexStore(), user_index=UserIndex())
        status, body = registry_service.register_user(
            {"principal_id": principal_id}
        )
        assert status == 200, body
        assert body["reputation"]["tasks_verified"] == 0
        assert body["reputation"]["verification_rate"] is None

        # Verification service: a COMPLETELY separate instance, its own
        # ReputationStore -- no Python object shared with registry_service.
        verifier = VerificationService(ReputationStore())
        v_status, v_body = verifier.process_evidence(
            _make_submission(principal_id)
        )
        assert v_status == 200, v_body
        assert v_body["verification_result"]["verdict"] == "verified"

        # No manual sync step: Registry's own read reflects it immediately.
        status, body = registry_service.get_user(principal_id)
        assert status == 200, body
        records = body["reputation_records"]
        assert len(records) == 1
        assert records[0]["capability_id"] == CAPABILITY_ID
        assert records[0]["tasks_verified"] == 1
        assert records[0]["tasks_rejected"] == 0
        assert records[0]["verification_rate"] == 1.0

        # And Registry's capability search picks it up too.
        status, body = registry_service.search(
            CAPABILITY_ID, min_reputation=0.9
        )
        assert status == 200
        # The agent above never registered a capability-search-visible card
        # (it's a plain user Principal here), so candidates is unrelated --
        # this call only proves search() reads the SAME table without error
        # and without needing a reputation_store injected.
        assert isinstance(body["candidates"], list)

    def test_registry_write_visible_via_verification_reputation_read(self):
        """The reverse direction: a reputation event recorded through
        Registry's user endpoint is immediately visible through an
        independent Verification Service ReputationStore's own read path."""
        principal_id = "agent:unification2-%s" % uuid.uuid4().hex[:8]

        registry_service = RegistryService(IndexStore(), user_index=UserIndex())
        registry_service.register_user({"principal_id": principal_id})
        status, body = registry_service.update_user_reputation(
            principal_id,
            {
                "task_id": "task-1",
                "verified": True,
                "capability_id": CAPABILITY_ID,
            },
        )
        assert status == 200, body

        # A brand new ReputationStore/ReputationRepository -- no object
        # shared with registry_service in any way.
        independent_store = ReputationStore()
        records = independent_store.get_reputation(
            principal_id, capability_id=CAPABILITY_ID
        )
        assert len(records) == 1
        assert records[0]["tasks_verified"] == 1
        assert records[0]["verification_rate"] == 1.0
