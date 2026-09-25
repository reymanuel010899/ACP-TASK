"""Tests for Agent Principal registration in the Registry (Phase B, unit U5).

Agents are first-class Principals: they register with their own
``principal_id`` (public side only — the Registry never receives private
keys, Decision 8), are created *by* a user Principal (``created_by``), and
accrue reputation independently through the SAME mechanism users do
(``POST /users/{principal_id}/reputation``).

Covered scenarios:
1. Register agent with created_by -> agent with principal_id + created_at
2. Duplicate principal_id -> 409
3. Missing/empty capabilities -> 422
4. Fresh agent -> neutral reputation (0/0/null)
5. Reputation recorded via existing endpoint reflects in GET /agents/{id}
6. Two agents have independent reputations
7. GET /agents?capability=<id> returns only matching agents
8. GET /agents/{nonexistent} -> 404
"""

import threading

import pytest
import requests

from libs.db import bind_organization_id
from registry.app import RegistryService, make_server
from registry.index_store import IndexStore


AGENT_CARD = {
    "name": "deploy-bot",
    "description": "Deploys infrastructure to AWS",
    "capabilities": ["aws.deploy", "terraform.apply"],
}


def make_card(name="deploy-bot", capabilities=None):
    # type: (str, list) -> dict
    card = dict(AGENT_CARD)
    card["name"] = name
    if capabilities is not None:
        card["capabilities"] = capabilities
    return card


@pytest.fixture
def index():
    return IndexStore()


@pytest.fixture
def service(index):
    service = RegistryService(index)
    bind_organization_id("org:test-registry")
    identity = service.agent_index._repo._identity
    if not identity.organization_exists("org:test-registry"):
        identity.create_organization("org:test-registry", "Registry Test")
    try:
        yield service
    finally:
        bind_organization_id(None)


def register_agent(service, principal_id, created_by="ed25519_user_alice",
                   capabilities=None, name="deploy-bot"):
    # type: (RegistryService, str, str, list, str) -> tuple
    return service.register_agent(
        {
            "agent_card": make_card(name=name, capabilities=capabilities),
            "principal_id": principal_id,
            "created_by": created_by,
        }
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestAgentRegistration:
    def test_register_agent_with_created_by(self, service):
        """Scenario 1: registration returns the agent with its principal_id
        and creation timestamp."""
        status, body = register_agent(
            service, "ed25519_agent_deploybot",
            created_by="ed25519_user_alice",
        )
        assert status == 200, body
        agent = body["agent"]
        assert agent["principal_id"] == "ed25519_agent_deploybot"
        assert agent["created_by"] == "ed25519_user_alice"
        assert agent["created_at"]
        assert agent["registered_at"]
        assert agent["agent_card"]["capabilities"] == [
            "aws.deploy", "terraform.apply",
        ]
        with service.agent_index._repo._db.connection() as conn:
            row = conn.execute(
                "SELECT organization_id FROM registry.agent_ownership "
                "WHERE principal_id = %s",
                ("ed25519_agent_deploybot",),
            ).fetchone()
        assert row == ("org:test-registry",)

    def test_registration_without_tenant_is_public_discovery_only(self, service):
        bind_organization_id(None)
        status, body = register_agent(service, "ed25519_agent_external")
        assert status == 200, body

        with service.agent_index._repo._db.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM registry.agent_ownership WHERE principal_id = %s",
                ("ed25519_agent_external",),
            ).fetchone()
        assert row is None

    def test_register_duplicate_principal_is_409(self, service):
        """Scenario 2: same agent principal_id twice -> 409."""
        register_agent(service, "ed25519_agent_dup")
        status, body = register_agent(service, "ed25519_agent_dup")
        assert status == 409, body
        assert "error" in body

    def test_list_all_agents_empty(self, service):
        """Full directory is empty before any registration."""
        status, body = service.list_all_agents()
        assert status == 200, body
        assert body == {"agents": []}

    def test_list_all_agents_returns_every_agent_with_reputation(self, service):
        """GET /agents (no capability) returns every registered agent, each
        with its aggregated reputation slice (neutral for fresh agents)."""
        register_agent(service, "ed25519_agent_one", name="one",
                       capabilities=["aws.deploy"])
        register_agent(service, "ed25519_agent_two", name="two",
                       capabilities=["terraform.apply", "k8s.manage"])
        status, body = service.list_all_agents()
        assert status == 200, body
        agents = body["agents"]
        assert len(agents) == 2
        ids = {item["agent"]["principal_id"] for item in agents}
        assert ids == {"ed25519_agent_one", "ed25519_agent_two"}
        for item in agents:
            assert item["agent"]["agent_card"]["name"] in {"one", "two"}
            # Fresh agents are reputation-neutral (0/0/null), not 0.0.
            assert item["reputation"]["verification_rate"] is None
            assert item["reputation"]["tasks_verified"] == 0
            assert item["reputation"]["tasks_rejected"] == 0

    def test_register_missing_capabilities_is_422(self, service):
        """Scenario 3a: agent_card without capabilities -> 422."""
        status, body = service.register_agent(
            {
                "agent_card": {"name": "bot", "description": "no caps"},
                "principal_id": "ed25519_agent_nocaps",
                "created_by": "ed25519_user_alice",
            }
        )
        assert status == 422, body
        assert "error" in body

    def test_register_empty_capabilities_is_422(self, service):
        """Scenario 3b: empty capabilities list -> 422."""
        status, body = register_agent(
            service, "ed25519_agent_emptycaps", capabilities=[]
        )
        assert status == 422, body

    def test_register_non_string_capabilities_is_422(self, service):
        """Scenario 3c: capabilities must be non-empty strings."""
        status, body = register_agent(
            service, "ed25519_agent_badcaps", capabilities=["aws.deploy", 7]
        )
        assert status == 422, body

    def test_register_missing_created_by_is_422(self, service):
        """created_by (the owning user Principal) is required."""
        status, body = service.register_agent(
            {
                "agent_card": make_card(),
                "principal_id": "ed25519_agent_orphan",
            }
        )
        assert status == 422, body

    def test_register_missing_principal_id_is_422(self, service):
        status, body = service.register_agent(
            {
                "agent_card": make_card(),
                "created_by": "ed25519_user_alice",
            }
        )
        assert status == 422, body

    def test_register_accepts_optional_public_key(self, service):
        """Decision 8: only the PUBLIC side is registered; public_key is an
        optional field for future signature verification."""
        status, body = service.register_agent(
            {
                "agent_card": make_card(),
                "principal_id": "ed25519_agent_keyed",
                "created_by": "ed25519_user_alice",
                "public_key": "ed25519-pub-abc123",
            }
        )
        assert status == 200, body
        assert body["agent"]["public_key"] == "ed25519-pub-abc123"


# ---------------------------------------------------------------------------
# Lookup + reputation
# ---------------------------------------------------------------------------


class TestAgentLookup:
    def test_get_fresh_agent_has_neutral_reputation(self, service):
        """Scenario 4: fresh agent reputation is 0/0/null (never 0.0)."""
        register_agent(service, "ed25519_agent_fresh")
        status, body = service.get_agent("ed25519_agent_fresh")
        assert status == 200, body
        assert body["agent"]["principal_id"] == "ed25519_agent_fresh"
        assert body["reputation"] == {
            "tasks_verified": 0,
            "tasks_rejected": 0,
            "verification_rate": None,
        }

    def test_get_nonexistent_agent_is_404(self, service):
        """Scenario 8: GET /agents/{nonexistent} -> 404."""
        status, body = service.get_agent("ed25519_agent_nobody")
        assert status == 404, body
        assert "error" in body

    def test_reputation_recorded_via_user_endpoint_reflects(self, service):
        """Scenario 5: agents are principals — the SAME reputation endpoint
        used for users works for agent principals, and GET /agents/{id}
        reflects the update."""
        register_agent(service, "ed25519_agent_worker")

        status, body = service.update_user_reputation(
            "ed25519_agent_worker",
            {
                "task_id": "task-a1",
                "verified": True,
                "capability_id": "aws.deploy",
            },
        )
        assert status == 200, body

        status, body = service.get_agent("ed25519_agent_worker")
        assert status == 200, body
        assert body["reputation"]["tasks_verified"] == 1
        assert body["reputation"]["tasks_rejected"] == 0
        assert body["reputation"]["verification_rate"] == 1.0

    def test_two_agents_have_independent_reputations(self, service):
        """Scenario 6: reputation is per-agent, never shared."""
        register_agent(service, "ed25519_agent_one")
        register_agent(service, "ed25519_agent_two")

        service.update_user_reputation(
            "ed25519_agent_one",
            {
                "task_id": "task-b1",
                "verified": True,
                "capability_id": "aws.deploy",
            },
        )
        service.update_user_reputation(
            "ed25519_agent_two",
            {
                "task_id": "task-b2",
                "verified": False,
                "capability_id": "aws.deploy",
            },
        )

        status, body_one = service.get_agent("ed25519_agent_one")
        assert status == 200
        status, body_two = service.get_agent("ed25519_agent_two")
        assert status == 200

        assert body_one["reputation"]["tasks_verified"] == 1
        assert body_one["reputation"]["tasks_rejected"] == 0
        assert body_one["reputation"]["verification_rate"] == 1.0

        assert body_two["reputation"]["tasks_verified"] == 0
        assert body_two["reputation"]["tasks_rejected"] == 1
        assert body_two["reputation"]["verification_rate"] == 0.0


class TestAgentCapabilitySearch:
    def test_find_by_capability_returns_matching_agents(self, service):
        """Scenario 7: only agents declaring the capability are returned."""
        register_agent(
            service, "ed25519_agent_aws",
            capabilities=["aws.deploy"], name="aws-bot",
        )
        register_agent(
            service, "ed25519_agent_reviewer",
            capabilities=["code.review"], name="review-bot",
        )

        status, body = service.list_agents("aws.deploy")
        assert status == 200, body
        principal_ids = [a["principal_id"] for a in body["agents"]]
        assert principal_ids == ["ed25519_agent_aws"]

    def test_find_by_capability_no_match_is_empty_list(self, service):
        register_agent(service, "ed25519_agent_solo")
        status, body = service.list_agents("quantum.compute")
        assert status == 200, body
        assert body["agents"] == []


# ---------------------------------------------------------------------------
# HTTP end-to-end
# ---------------------------------------------------------------------------


@pytest.fixture
def http_registry():
    """HTTP registry server for testing."""
    service = RegistryService(IndexStore())
    bind_organization_id("org:test-registry-http")
    identity = service.agent_index._repo._identity
    if not identity.organization_exists("org:test-registry-http"):
        identity.create_organization(
            "org:test-registry-http", "Registry HTTP Test"
        )
    bind_organization_id(None)
    server = make_server(port=0, service=service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = "http://%s:%d" % server.server_address[:2]
    try:
        yield base_url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def http_register_agent(base_url, principal_id, capabilities=None):
    # type: (str, str, list) -> requests.Response
    return requests.post(
        base_url + "/agents/register",
        json={
            "agent_card": make_card(capabilities=capabilities),
            "principal_id": principal_id,
            "created_by": "ed25519_user_alice",
        },
        headers={"X-Organization-Id": "org:test-registry-http"},
        timeout=5,
    )


class TestAgentHTTPEndToEnd:
    def test_http_register_agent(self, http_registry):
        """HTTP POST /agents/register registers an agent Principal."""
        resp = http_register_agent(http_registry, "ed25519_agent_http")
        assert resp.status_code == 200
        body = resp.json()
        assert body["agent"]["principal_id"] == "ed25519_agent_http"
        assert body["agent"]["registered_at"]

    def test_http_register_duplicate_is_409(self, http_registry):
        http_register_agent(http_registry, "ed25519_agent_http_dup")
        resp = http_register_agent(http_registry, "ed25519_agent_http_dup")
        assert resp.status_code == 409

    def test_http_register_empty_capabilities_is_422(self, http_registry):
        resp = http_register_agent(
            http_registry, "ed25519_agent_http_nocaps", capabilities=[]
        )
        assert resp.status_code == 422

    def test_http_get_agent_with_reputation(self, http_registry):
        """HTTP GET /agents/{principal_id} returns metadata + reputation."""
        http_register_agent(http_registry, "ed25519_agent_http_get")
        resp = requests.get(
            http_registry + "/agents/ed25519_agent_http_get", timeout=5
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["agent"]["principal_id"] == "ed25519_agent_http_get"
        assert body["reputation"] == {
            "tasks_verified": 0,
            "tasks_rejected": 0,
            "verification_rate": None,
        }

    def test_http_get_nonexistent_agent_is_404(self, http_registry):
        resp = requests.get(
            http_registry + "/agents/ed25519_agent_ghost", timeout=5
        )
        assert resp.status_code == 404

    def test_http_reputation_endpoint_works_for_agents(self, http_registry):
        """The existing user reputation endpoint accepts agent principals."""
        http_register_agent(http_registry, "ed25519_agent_http_rep")
        resp = requests.post(
            http_registry + "/agents/ed25519_agent_http_rep".replace(
                "/agents/", "/users/"
            ) + "/reputation",
            json={
                "task_id": "task-http-a1",
                "verified": True,
                "capability_id": "aws.deploy",
            },
            timeout=5,
        )
        assert resp.status_code == 200

        resp = requests.get(
            http_registry + "/agents/ed25519_agent_http_rep", timeout=5
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["reputation"]["tasks_verified"] == 1
        assert body["reputation"]["verification_rate"] == 1.0

    def test_http_list_agents_by_capability(self, http_registry):
        """HTTP GET /agents?capability=aws.deploy filters agents."""
        http_register_agent(
            http_registry, "ed25519_agent_http_aws",
            capabilities=["aws.deploy"],
        )
        http_register_agent(
            http_registry, "ed25519_agent_http_review",
            capabilities=["code.review"],
        )
        resp = requests.get(
            http_registry + "/agents",
            params={"capability": "aws.deploy"},
            timeout=5,
        )
        assert resp.status_code == 200
        body = resp.json()
        principal_ids = [a["principal_id"] for a in body["agents"]]
        assert principal_ids == ["ed25519_agent_http_aws"]

    def test_http_list_agents_no_match_is_empty(self, http_registry):
        resp = requests.get(
            http_registry + "/agents",
            params={"capability": "nothing.here"},
            timeout=5,
        )
        assert resp.status_code == 200
        assert resp.json()["agents"] == []


# ---------------------------------------------------------------------------
# Backward compatibility: legacy agent-card registrations still resolve
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_legacy_registration_lookup_still_works(self, service):
        """GET /agents/{id} still serves U4 agent-card registrations."""
        key = service.create_api_key()
        status, body = service.register(
            {
                "api_key": key,
                "principal_id": "agent:legacy",
                "agent_card": {
                    "name": "legacy",
                    "capabilities": {
                        "extensions": [
                            {
                                "uri": "https://treessera.com/"
                                "extensions/trust/v1"
                            }
                        ]
                    },
                    "skills": [{"id": "legacy.cap"}],
                },
            }
        )
        assert status == 200, body

        status, body = service.get_agent("agent:legacy")
        assert status == 200, body
        assert body["registration"]["principal_id"] == "agent:legacy"
