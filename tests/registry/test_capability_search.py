"""Tests for the AgentTrust Reference Registry (unit U4).

Test-first: these tests define the contract of ``registry.app`` /
``registry.index_store`` before the implementation exists. The registry is
exercised via direct calls to :class:`RegistryService` (no HTTP); the HTTP
layer is covered at the end with a threaded stdlib server.

Covered plan scenarios:

- Happy path: two agents with distinct capabilities; searching one capability
  returns only the matching agent.
- Edge: ``min_reputation`` excludes a capability-matching agent with no
  reputation history (neutral is not "passing" an explicit threshold);
  registration without a valid invite/API key is 403.
- Integration: reputation updates made through the U3 VerificationService
  (sharing one in-process ReputationStore) are reflected in registry searches
  with no manual sync step.
- HTTP end-to-end: admin key -> register -> search on a threaded server.
"""

import base64
import hashlib
import json
import threading
import uuid

import pytest
import requests
from nacl.signing import SigningKey

from registry.app import RegistryService, TRUST_EXTENSION_URI, make_server
from registry.index_store import IndexStore
from services.verification.app import VerificationService
from services.verification.reputation_store import ReputationStore

TERRAFORM_CAP = "terraform.generate"
REVIEW_CAP = "code.review"

VALID_HCL = """
resource "aws_s3_bucket" "demo" {
  bucket = "agenttrust-demo"
}
"""


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def make_card(name, skill_ids, principal_id, with_extension=True):
    """A realistic A2A Agent Card (same shape as examples/)."""
    extensions = []
    if with_extension:
        extensions.append(
            {
                "uri": TRUST_EXTENSION_URI,
                "description": "AgentTrust trust layer.",
                "required": False,
                "params": {"principal_id": principal_id},
            }
        )
    return {
        "name": name,
        "description": "%s test agent" % name,
        "url": "https://agents.example.com/%s/a2a/v1" % name.lower(),
        "version": "1.0.0",
        "protocolVersion": "0.3.0",
        "preferredTransport": "JSONRPC",
        "capabilities": {"streaming": False, "extensions": extensions},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {
                "id": skill_id,
                "name": skill_id,
                "description": "Skill %s" % skill_id,
                "tags": ["test"],
            }
            for skill_id in skill_ids
        ],
    }


def make_identity(principal_id):
    sk = SigningKey.generate()
    public_key = base64.b64encode(bytes(sk.verify_key)).decode("ascii")
    principal = {
        "principal_id": principal_id,
        "public_key": public_key,
        "key_algorithm": "ed25519",
    }
    return sk, principal


def make_verified_submission(sk, principal, hcl=VALID_HCL):
    """A full U3 evidence submission payload for the given identity."""
    session_id = "sess-%s" % uuid.uuid4().hex
    claims = {
        "session_id": session_id,
        "principal_id": principal["principal_id"],
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
        "principal_id": principal["principal_id"],
        "issued_at": "2026-07-14T10:00:00Z",
        "expires_at": "2099-01-01T00:00:00Z",
        "principal_signature": signature,
    }
    evidence = {
        "evidence_id": "ev-%s" % uuid.uuid4().hex,
        "session_id": session_id,
        "capability_id": TERRAFORM_CAP,
        "schema_valid": True,
        "tests_passed": True,
        "artifact_hashes": {
            "main.tf": hashlib.sha256(hcl.encode("utf-8")).hexdigest()
        },
        "created_at": "2026-07-14T10:05:00Z",
        "extensions": {"terraform_hcl": hcl},
    }
    return {"evidence": evidence, "session": session, "principal": principal}


@pytest.fixture
def index():
    return IndexStore()


@pytest.fixture
def reputation_store():
    return ReputationStore()


@pytest.fixture
def service(index, reputation_store):
    return RegistryService(index, reputation_store=reputation_store)


def register_agent(service, principal_id, skill_ids, name="Agent"):
    api_key = service.create_api_key()
    status, body = service.register(
        {
            "agent_card": make_card(name, skill_ids, principal_id),
            "principal_id": principal_id,
            "api_key": api_key,
        }
    )
    assert status == 200, body
    return body


# ---------------------------------------------------------------------------
# Happy path: capability search returns only matching agents
# ---------------------------------------------------------------------------


class TestCapabilitySearch:
    def test_search_returns_only_matching_capability(self, service):
        register_agent(
            service, "agent:terraformer", [TERRAFORM_CAP], name="TerraformSmith"
        )
        register_agent(
            service, "agent:reviewer", [REVIEW_CAP], name="ReviewBot"
        )

        status, body = service.search(TERRAFORM_CAP)
        assert status == 200
        candidates = body["candidates"]
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate["principal_id"] == "agent:terraformer"
        assert candidate["agent_card"]["name"] == "TerraformSmith"
        # Neutral reputation (no history): counts 0, rate null -- never 0.0.
        summary = candidate["reputation_summary"]
        assert summary["capability_id"] == TERRAFORM_CAP
        assert summary["tasks_verified"] == 0
        assert summary["tasks_rejected"] == 0
        assert summary["verification_rate"] is None

    def test_search_unknown_capability_is_empty(self, service):
        register_agent(service, "agent:terraformer", [TERRAFORM_CAP])
        status, body = service.search("nonexistent.capability")
        assert status == 200
        assert body["candidates"] == []

    def test_agent_with_multiple_skills_matches_each(self, service):
        register_agent(
            service, "agent:poly", [TERRAFORM_CAP, REVIEW_CAP], name="Poly"
        )
        for cap in (TERRAFORM_CAP, REVIEW_CAP):
            status, body = service.search(cap)
            assert status == 200
            assert [c["principal_id"] for c in body["candidates"]] == [
                "agent:poly"
            ]

    def test_get_agent_returns_registration(self, service):
        register_agent(service, "agent:terraformer", [TERRAFORM_CAP])
        status, body = service.get_agent("agent:terraformer")
        assert status == 200
        assert body["registration"]["principal_id"] == "agent:terraformer"
        assert body["registration"]["agent_card"]["skills"][0]["id"] == (
            TERRAFORM_CAP
        )

    def test_get_unknown_agent_404(self, service):
        status, body = service.get_agent("agent:nobody")
        assert status == 404


# ---------------------------------------------------------------------------
# Anti-Sybil friction: registration requires a registry-issued API key
# ---------------------------------------------------------------------------


class TestRegistrationGate:
    def test_registration_without_api_key_is_403(self, service, index):
        status, body = service.register(
            {
                "agent_card": make_card("Free", [TERRAFORM_CAP], "agent:free"),
                "principal_id": "agent:free",
            }
        )
        assert status == 403
        # Nothing indexed.
        assert service.search(TERRAFORM_CAP)[1]["candidates"] == []

    def test_registration_with_bogus_api_key_is_403(self, service):
        status, _ = service.register(
            {
                "agent_card": make_card("Free", [TERRAFORM_CAP], "agent:free"),
                "principal_id": "agent:free",
                "api_key": "not-a-real-key",
            }
        )
        assert status == 403

    def test_card_without_trust_extension_is_422(self, service):
        api_key = service.create_api_key()
        card = make_card(
            "NoTrust", [TERRAFORM_CAP], "agent:notrust", with_extension=False
        )
        status, body = service.register(
            {
                "agent_card": card,
                "principal_id": "agent:notrust",
                "api_key": api_key,
            }
        )
        assert status == 422
        assert service.search(TERRAFORM_CAP)[1]["candidates"] == []

    def test_api_keys_seeded_from_file(self, tmp_path, reputation_store):
        keys_path = tmp_path / "keys.json"
        keys_path.write_text(json.dumps(["seeded-key-1"]))
        index = IndexStore(api_keys_path=str(keys_path))
        service = RegistryService(index, reputation_store=reputation_store)
        status, _ = service.register(
            {
                "agent_card": make_card("Seeded", [TERRAFORM_CAP], "agent:s"),
                "principal_id": "agent:s",
                "api_key": "seeded-key-1",
            }
        )
        assert status == 200


# ---------------------------------------------------------------------------
# Edge: min_reputation excludes agents with no history (neutral != passing)
# ---------------------------------------------------------------------------


class TestMinReputationFilter:
    def test_no_history_agent_excluded_by_min_reputation(self, service):
        register_agent(service, "agent:newcomer", [TERRAFORM_CAP])

        # Without the filter the agent is found...
        status, body = service.search(TERRAFORM_CAP)
        assert [c["principal_id"] for c in body["candidates"]] == [
            "agent:newcomer"
        ]
        # ...but an explicit min_reputation excludes a null-rate agent.
        status, body = service.search(TERRAFORM_CAP, min_reputation=0.9)
        assert status == 200
        assert body["candidates"] == []

    def test_below_threshold_agent_excluded(
        self, service, reputation_store
    ):
        register_agent(service, "agent:sloppy", [TERRAFORM_CAP])
        reputation_store.record_verdict(
            "agent:sloppy", TERRAFORM_CAP, "verified"
        )
        reputation_store.record_verdict(
            "agent:sloppy", TERRAFORM_CAP, "rejected"
        )  # rate 0.5

        _, body = service.search(TERRAFORM_CAP, min_reputation=0.9)
        assert body["candidates"] == []
        _, body = service.search(TERRAFORM_CAP, min_reputation=0.5)
        assert [c["principal_id"] for c in body["candidates"]] == [
            "agent:sloppy"
        ]


# ---------------------------------------------------------------------------
# Integration with U3: shared ReputationStore, no manual sync
# ---------------------------------------------------------------------------


class TestVerificationServiceIntegration:
    def test_u3_verdicts_show_up_in_search(self, index, reputation_store):
        registry = RegistryService(index, reputation_store=reputation_store)
        verifier = VerificationService(reputation_store)

        sk, principal = make_identity("agent:terraformer")
        register_agent(
            registry, "agent:terraformer", [TERRAFORM_CAP], name="TFSmith"
        )

        # Before any verified work: excluded by an explicit threshold.
        _, body = registry.search(TERRAFORM_CAP, min_reputation=0.9)
        assert body["candidates"] == []

        # A task verified through the U3 pipeline...
        status, resp = verifier.process_evidence(
            make_verified_submission(sk, principal)
        )
        assert status == 200
        assert resp["verification_result"]["verdict"] == "verified"

        # ...is reflected in the very next registry search, no sync step.
        _, body = registry.search(TERRAFORM_CAP, min_reputation=0.9)
        assert len(body["candidates"]) == 1
        summary = body["candidates"][0]["reputation_summary"]
        assert summary["tasks_verified"] == 1
        assert summary["tasks_rejected"] == 0
        assert summary["verification_rate"] == 1.0

    def test_verification_service_down_treated_as_neutral(self, index):
        # HTTP reputation mode pointing at a dead endpoint: search still
        # works, reputation is unknown/neutral.
        registry = RegistryService(
            index, verification_url="http://127.0.0.1:9", http_timeout=0.5
        )
        register_agent(registry, "agent:lonely", [TERRAFORM_CAP])

        status, body = registry.search(TERRAFORM_CAP)
        assert status == 200
        (candidate,) = body["candidates"]
        assert candidate["reputation_summary"]["verification_rate"] is None
        # And an explicit min_reputation excludes it (unknown != passing).
        _, body = registry.search(TERRAFORM_CAP, min_reputation=0.5)
        assert body["candidates"] == []


# ---------------------------------------------------------------------------
# HTTP end-to-end: admin key -> register -> search
# ---------------------------------------------------------------------------


@pytest.fixture
def http_registry():
    store = ReputationStore()
    server = make_server(port=0, reputation_store=store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = "http://%s:%d" % server.server_address[:2]
    try:
        yield base_url, store
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class TestHTTPEndToEnd:
    def test_admin_key_register_search(self, http_registry):
        base_url, store = http_registry

        health = requests.get(base_url + "/healthz", timeout=5)
        assert health.status_code == 200

        # Bootstrap: mint an invite/API key from the admin surface.
        minted = requests.post(base_url + "/admin/api-keys", timeout=5)
        assert minted.status_code == 200
        api_key = minted.json()["api_key"]
        assert api_key

        # Registration without the key is refused.
        card = make_card("TFSmith", [TERRAFORM_CAP], "agent:terraformer")
        refused = requests.post(
            base_url + "/register",
            json={"agent_card": card, "principal_id": "agent:terraformer"},
            timeout=5,
        )
        assert refused.status_code == 403

        # With the key it succeeds.
        accepted = requests.post(
            base_url + "/register",
            json={
                "agent_card": card,
                "principal_id": "agent:terraformer",
                "api_key": api_key,
            },
            timeout=5,
        )
        assert accepted.status_code == 200

        # Search finds it, with a neutral reputation summary.
        found = requests.get(
            base_url + "/search",
            params={"capability": TERRAFORM_CAP},
            timeout=5,
        )
        assert found.status_code == 200
        (candidate,) = found.json()["candidates"]
        assert candidate["principal_id"] == "agent:terraformer"
        assert candidate["reputation_summary"]["verification_rate"] is None

        # min_reputation over HTTP: neutral agent excluded until the shared
        # store records a verified task.
        empty = requests.get(
            base_url + "/search",
            params={"capability": TERRAFORM_CAP, "min_reputation": "0.9"},
            timeout=5,
        )
        assert empty.json()["candidates"] == []
        store.record_verdict("agent:terraformer", TERRAFORM_CAP, "verified")
        full = requests.get(
            base_url + "/search",
            params={"capability": TERRAFORM_CAP, "min_reputation": "0.9"},
            timeout=5,
        )
        (candidate,) = full.json()["candidates"]
        assert candidate["reputation_summary"]["verification_rate"] == 1.0

        # Registration lookup (principal ids contain ':', so quote the path).
        agent = requests.get(
            base_url + "/agents/agent%3Aterraformer", timeout=5
        )
        assert agent.status_code == 200
        assert agent.json()["registration"]["agent_card"]["name"] == "TFSmith"

    def test_search_requires_capability_param(self, http_registry):
        base_url, _ = http_registry
        resp = requests.get(base_url + "/search", timeout=5)
        assert resp.status_code == 400

    def test_bad_min_reputation_is_400(self, http_registry):
        base_url, _ = http_registry
        resp = requests.get(
            base_url + "/search",
            params={"capability": TERRAFORM_CAP, "min_reputation": "high"},
            timeout=5,
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# U4 (auth): optional admin token on /admin/api-keys
# ---------------------------------------------------------------------------


@pytest.fixture
def http_registry_secured():
    server = make_server(port=0, admin_token="adm1n")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = "http://%s:%d" % server.server_address[:2]
    try:
        yield base_url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class TestAdminAuth:
    def test_open_admin_mints_without_token(self, http_registry):
        # Default (no admin_token): the admin surface is open (compat).
        base_url, _ = http_registry
        resp = requests.post(base_url + "/admin/api-keys", timeout=5)
        assert resp.status_code == 200
        assert resp.json()["api_key"]

    def test_secured_admin_rejects_without_token(self, http_registry_secured):
        resp = requests.post(http_registry_secured + "/admin/api-keys", timeout=5)
        assert resp.status_code == 401
        assert resp.headers.get("WWW-Authenticate") == "Bearer"

    def test_secured_admin_rejects_wrong_token(self, http_registry_secured):
        resp = requests.post(
            http_registry_secured + "/admin/api-keys",
            headers={"Authorization": "Bearer nope"},
            timeout=5,
        )
        assert resp.status_code == 401

    def test_secured_admin_accepts_right_token(self, http_registry_secured):
        resp = requests.post(
            http_registry_secured + "/admin/api-keys",
            headers={"Authorization": "Bearer adm1n"},
            timeout=5,
        )
        assert resp.status_code == 200
        assert resp.json()["api_key"]

    def test_secured_admin_does_not_affect_search(self, http_registry_secured):
        # /search is unaffected by the admin token.
        resp = requests.get(
            http_registry_secured + "/search",
            params={"capability": TERRAFORM_CAP},
            timeout=5,
        )
        assert resp.status_code == 200
