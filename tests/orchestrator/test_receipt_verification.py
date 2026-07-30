"""Provider-grounded receipt verification and broker submission (U11/U12)."""

from agents.orchestrator.action_repository import ActionRepository
from agents.orchestrator.attestation import ExecutionAttestor
from libs.connectors.base import ProviderAuthority
from libs.signing import generate_keypair
from services.action_broker.app import ActionBroker
from services.verification.app import VerificationService
from services.verification.verifiers.google import GoogleReceiptVerifier


NOW = 1_700_000_000


class MemoryStore(object):
    def __init__(self):
        self.results = {}
        self.verdicts = []
        self.portfolio = []
        self.revoked = set()

    def get_result(self, evidence_id):
        return self.results.get(evidence_id)

    def put_result(self, result):
        self.results[result["evidence_id"]] = dict(result)

    def record_verdict(self, principal_id, capability_id, verdict):
        self.verdicts.append((principal_id, capability_id, verdict))
        return {
            "principal_id": principal_id,
            "capability_id": capability_id,
            "tasks_verified": len(self.verdicts),
            "tasks_rejected": 0,
            "verification_rate": 1.0,
        }

    def add_portfolio_entry(self, principal_id, capability_id, result):
        if result["verdict"] == "verified":
            self.portfolio.append((principal_id, capability_id, result))

    def is_revoked(self, *values):
        return any(value in self.revoked for value in values)


class Gateway(object):
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = result or {
            "provider": "google",
            "capability_id": "calendar.create",
            "provider_id": "event-7",
            "user_principal_id": "user:alice",
            "credential_id": "credential:google",
            "material": {"summary": "Interview"},
        }
        self.error = error

    def read_receipt(
        self,
        user_principal_id,
        credential_id,
        capability_id,
        provider_id,
    ):
        self.calls.append(
            (
                user_principal_id,
                credential_id,
                capability_id,
                provider_id,
            )
        )
        if self.error:
            raise self.error
        return dict(self.result)


def _service(gateway=None):
    key = generate_keypair()
    attestor = ExecutionAttestor(
        "broker-key-1", key.signing_key, clock=lambda: NOW
    )
    store = MemoryStore()
    verifier = GoogleReceiptVerifier(gateway or Gateway())
    service = VerificationService(
        store,
        broker_keys={"broker-key-1": key.public_key_b64()},
        receipt_verifiers={"google": verifier},
    )
    return attestor, store, service


def _evidence(attestor, **overrides):
    fields = {
        "task_id": "task-1",
        "user_principal_id": "user:alice",
        "agent_principal_id": "agent:calendar",
        "credential_id": "credential:google",
        "capability_id": "calendar.create",
        "approved_payload_hash": "a" * 64,
        "provider_receipt": {
            "provider": "google",
            "capability_id": "calendar.create",
            "provider_id": "event-7",
        },
        "idempotency_key": "action-1",
        "outcome": "succeeded",
        "approved_payload": {"event": {"summary": "Interview"}},
    }
    fields.update(overrides)
    attestation = attestor.create(**fields)
    return {
        "evidence_id": attestation["attestation_id"],
        "capability_id": attestation["capability_id"],
        "execution_attestation": attestation,
    }


def test_valid_bound_receipt_verifies_and_only_then_credits_agent():
    gateway = Gateway()
    attestor, store, service = _service(gateway)

    status, response = service.process_execution_evidence(
        _evidence(attestor)
    )

    assert status == 200
    assert response["evidence_status"] == "verified"
    assert response["verification_result"]["verdict"] == "verified"
    assert store.verdicts == [
        ("agent:calendar", "calendar.create", "verified")
    ]
    assert gateway.calls == [
        (
            "user:alice",
            "credential:google",
            "calendar.create",
            "event-7",
        )
    ]


def test_replay_and_provider_ownership_or_material_mismatch_do_not_credit():
    attestor, store, service = _service()
    evidence = _evidence(attestor)
    service.process_execution_evidence(evidence)

    status, response = service.process_execution_evidence(evidence)
    assert status == 409
    assert response["evidence_status"] == "rejected"
    assert len(store.verdicts) == 1

    wrong_gateway = Gateway(
        result={
            "provider": "google",
            "capability_id": "calendar.create",
            "provider_id": "event-7",
            "user_principal_id": "user:bob",
            "credential_id": "credential:google",
            "material": {"summary": "Changed"},
        }
    )
    other_attestor, other_store, other_service = _service(wrong_gateway)
    _, mismatch = other_service.process_execution_evidence(
        _evidence(other_attestor)
    )
    assert mismatch["evidence_status"] == "rejected"
    assert other_store.verdicts == []


def test_denied_gateway_read_is_unverified_and_does_not_change_reputation():
    attestor, store, service = _service(
        Gateway(error=PermissionError("permission denied"))
    )

    status, response = service.process_execution_evidence(
        _evidence(attestor)
    )

    assert status == 200
    assert response["evidence_status"] == "unverified"
    assert "verification_result" not in response
    assert store.verdicts == []


def test_revoked_agent_cannot_submit_broker_execution_evidence():
    attestor, store, service = _service()
    store.revoked.add("agent:calendar")

    status, response = service.process_execution_evidence(
        _evidence(attestor)
    )

    assert status == 403
    assert response["evidence_status"] == "rejected"
    assert store.verdicts == []


class Vault(object):
    def use_managed_oauth(self, _credential_id, _identity, operation):
        return operation(b"provider-secret-token")


class Executor(object):
    def execute(self, capability, _payload, _context):
        return {
            "provider": "google",
            "capability_id": capability,
            "provider_id": "event-7",
        }

    def read(self, _capability, _payload, _context):
        return {"items": []}


class Sessions(object):
    pass


class Connector(object):
    def refresh(self, refresh_token):
        assert refresh_token == "provider-secret-token"
        return ProviderAuthority(
            "access-token",
            3600,
            frozenset(
                {
                    "https://www.googleapis.com/auth/calendar.events",
                    "https://www.googleapis.com/auth/calendar.readonly",
                }
            ),
        )

    def scope_catalog(self):
        return {
            "calendar.create": "https://www.googleapis.com/auth/calendar.events",
            "calendar.read": "https://www.googleapis.com/auth/calendar.readonly",
        }


def _broker_stack(tmp_path, submitter, attestor=None):
    actions = ActionRepository(str(tmp_path / "actions.sqlite"))
    if attestor is None:
        key = generate_keypair()
        attestor = ExecutionAttestor(
            "broker-key-1", key.signing_key, clock=lambda: NOW
        )
    broker = ActionBroker(
        actions,
        Sessions(),
        Vault(),
        Executor(),
        clock=lambda: NOW,
        identity_verifier=lambda *_: True,
        agent_url_resolver=lambda _principal: "https://agent.example/a2a",
        credential_authorizer=lambda _binding: True,
        credential_connector=Connector(),
        attestor=attestor,
        evidence_submitter=submitter,
    )
    payload = {"event": {"summary": "Interview"}}
    proposal = actions.create_proposal(
        "user:alice",
        "agent:calendar",
        "credential:google",
        "calendar.create",
        payload,
        NOW + 300,
    )
    actions.decide(proposal["proposal_id"], 1, "user:alice", True, NOW)
    binding = {
        "proposal_id": proposal["proposal_id"],
        "version": proposal["version"],
        "user_principal_id": "user:alice",
        "agent_principal_id": "agent:calendar",
        "task_id": "task-1",
        "credential_id": "credential:google",
        "capability_id": "calendar.create",
        "payload_hash": proposal["payload_hash"],
        "idempotency_key": proposal["idempotency_key"],
        "agent_url": "https://agent.example/a2a",
    }
    lease = actions.issue_lease(
        "user:alice",
        "agent:calendar",
        "task-1",
        "credential:google",
        ["calendar.create"],
        NOW + 60,
    )
    return broker, lease, binding, payload


def test_broker_submits_signed_evidence_and_returns_verified_outcome(tmp_path):
    key = generate_keypair()
    attestor = ExecutionAttestor(
        "broker-key-1", key.signing_key, clock=lambda: NOW
    )
    store = MemoryStore()
    service = VerificationService(
        store,
        broker_keys={"broker-key-1": key.public_key_b64()},
        receipt_verifiers={"google": GoogleReceiptVerifier(Gateway())},
    )
    broker, lease, binding, payload = _broker_stack(
        tmp_path, service.process_execution_evidence, attestor=attestor
    )
    status, response = broker.execute(lease, binding, payload)

    assert status == 200
    assert response["evidence_status"] == "verified"
    assert response["verification_result"]["verdict"] == "verified"
    assert response["execution_attestation"]["agent_principal_id"] == (
        "agent:calendar"
    )
    assert store.verdicts == [
        ("agent:calendar", "calendar.create", "verified")
    ]
    assert "provider-secret-token" not in str(response)


def test_verifier_outage_is_pending_and_reads_emit_no_attestation(tmp_path):
    broker, lease, binding, payload = _broker_stack(
        tmp_path, lambda _evidence: (_ for _ in ()).throw(RuntimeError())
    )
    status, response = broker.execute(lease, binding, payload)
    assert status == 200
    assert response["evidence_status"] == "pending"
    broker.actions.close()

    restarted = ActionBroker(
        ActionRepository(str(tmp_path / "actions.sqlite")),
        Sessions(),
        Vault(),
        Executor(),
        clock=lambda: NOW,
        identity_verifier=lambda *_: True,
        agent_url_resolver=lambda _principal: "https://agent.example/a2a",
        credential_authorizer=lambda _binding: True,
        credential_connector=Connector(),
        attestor=broker.attestor,
        evidence_submitter=lambda _evidence: {
            "evidence_status": "verified"
        },
    )
    replay_status, replay = restarted.execute(lease, binding, payload)
    assert replay_status == 200
    assert replay == response

    read_binding = dict(binding, capability_id="calendar.read")
    read_lease = restarted.actions.issue_lease(
        "user:alice",
        "agent:calendar",
        "task-1",
        "credential:google",
        ["calendar.read"],
        NOW + 60,
    )
    status, response = restarted.execute(read_lease, read_binding, {})
    assert status == 200
    assert "execution_attestation" not in response
