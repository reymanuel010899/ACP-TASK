"""Integration tests for cross-app agent operations (Phase B, U11).

Proves end-to-end that agents operate ACROSS app boundaries: an agent
registered ONCE in the Registry works in both the Marketplace and the Gig
Board, reputation earned in either app is visible everywhere (Registry,
Agent Marketplace, federation clients), and the full Phase B stack
(Registry + Vault + Agent Marketplace + both apps) interoperates.

All servers run on EPHEMERAL ports (port=0), never fixed ports. One fixture
(``stack``) spins the FULL stack per test, wired together exactly the way
production wiring works (--registry-url / --vault-url equivalents via
``make_server`` kwargs, service registration via ``POST /apps/register``).

Note on per-capability reputation reads (scenarios 3, 4, 10): the Registry
exposes per-capability reputation records only via ``GET /users/{id}``,
which answers 404 for agent-only principals (``GET /agents/{id}`` returns
the AGGREGATED reputation). Reputation records live in one shared store
keyed by (principal, capability), so these tests additionally register the
agent's principal_id through ``POST /auth/register`` — a public-API-only
step that makes the per-capability breakdown readable without touching any
production code.
"""

import threading

import pytest
import requests

from agent_marketplace.app import make_server as make_agent_marketplace_server
from agents.marketplace_coordinator.agent import MarketplaceCoordinatorAgent
from apps.gig_board.server.app import make_server as make_gig_board_server
from apps.marketplace.server.app import make_server as make_marketplace_server
from libs.agent_coordination import AgentCoordinator
from libs.agent_marketplace_client import AgentMarketplaceClient
from libs.federation_client import FederationClient
from registry.app import make_server as make_registry_server
from vault.app import make_server as make_vault_server

TIMEOUT = 5.0
MARKETPLACE_CAP = "marketplace.tasks"
GIG_BOARD_CAP = "gig-board.gigs"


# ---------------------------------------------------------------------------
# Helpers (U10 style: raw HTTP against real servers)
# ---------------------------------------------------------------------------


def _start(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def _url(server):
    host, port = server.server_address[:2]
    return "http://%s:%d" % (host, port)


def _register_user(registry_url, principal_id):
    resp = requests.post(
        "%s/auth/register" % registry_url,
        json={"principal_id": principal_id},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _register_agent(registry_url, principal_id, capabilities,
                    created_by="user:agent-owner"):
    resp = requests.post(
        "%s/agents/register" % registry_url,
        json={
            "principal_id": principal_id,
            "created_by": created_by,
            "agent_card": {
                "name": principal_id,
                "description": "cross-app work agent",
                "capabilities": capabilities,
            },
        },
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _register_app(registry_url, app_id, endpoint, capabilities,
                  **service_flags):
    payload = {
        "app_id": app_id,
        "app_endpoint": endpoint,
        "p2p_endpoint": endpoint,
        "capabilities": capabilities,
    }
    payload.update(service_flags)
    resp = requests.post(
        "%s/apps/register" % registry_url, json=payload, timeout=TIMEOUT
    )
    assert resp.status_code == 200, resp.text


def _p2p(app_url, requester, request_type, input=None,  # noqa: A002
         capability=MARKETPLACE_CAP):
    """Raw P2P request straight to the app (precise status assertions)."""
    return requests.post(
        "%s/p2p/request" % app_url,
        json={
            "requester_principal_id": requester,
            "request_type": request_type,
            "capability_id": capability,
            "input": input if input is not None else {},
        },
        timeout=TIMEOUT,
    )


def _create_task(marketplace_url, author, description):
    resp = requests.post(
        "%s/api/tasks" % marketplace_url,
        json={"principal_id": author, "description": description},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["task"]


def _get_bids(marketplace_url, task_id):
    resp = requests.get(
        "%s/api/tasks/%s/bids" % (marketplace_url, task_id), timeout=TIMEOUT
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["bids"]


def _accept_bid(marketplace_url, task_id, bid_id, author):
    return requests.post(
        "%s/api/tasks/%s/bids/%s/accept" % (marketplace_url, task_id, bid_id),
        json={"author_principal": author},
        timeout=TIMEOUT,
    )


def _complete_task(marketplace_url, task_id, author, outcome="great work"):
    return requests.post(
        "%s/api/negotiations/%s/complete" % (marketplace_url, task_id),
        json={"author_principal": author, "outcome": outcome},
        timeout=TIMEOUT,
    )


def _agent_detail(registry_url, agent_principal_id):
    resp = requests.get(
        "%s/agents/%s" % (registry_url, agent_principal_id), timeout=TIMEOUT
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _agent_reputation(registry_url, agent_principal_id):
    return _agent_detail(registry_url, agent_principal_id)["reputation"]


def _reputation_records(registry_url, principal_id):
    """Per-capability reputation records (requires the principal to ALSO
    be mirrored into the user store; see module docstring)."""
    resp = requests.get(
        "%s/users/%s" % (registry_url, principal_id), timeout=TIMEOUT
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["reputation_records"]


def _complete_marketplace_task_via_agent(stack, agent_id, author,
                                         description):
    """Full marketplace lifecycle for one agent: create -> bid -> accept
    -> deliver -> complete. Returns the task id."""
    task = _create_task(stack.marketplace, author, description)
    bid = _p2p(
        stack.marketplace, agent_id, "submit.work_bid",
        input={"task_id": task["id"], "proposed_terms": "2 credits"},
    )
    assert bid.status_code == 200, bid.text
    bid = bid.json()["result"]["bid"]
    assert _accept_bid(
        stack.marketplace, task["id"], bid["bid_id"], author
    ).status_code == 200
    delivered = _p2p(
        stack.marketplace, agent_id, "submit.work_result",
        input={"task_id": task["id"], "result_summary": "work delivered"},
    )
    assert delivered.status_code == 200, delivered.text
    done = _complete_task(stack.marketplace, task["id"], author)
    assert done.status_code == 200, done.text
    assert done.json()["task"]["status"] == "completed"
    return task["id"]


def _complete_gig_via_agent(stack, agent_id, buyer, service_name="service"):
    """Full gig-board lifecycle for one agent: register.service (P2P) ->
    buyer creates gig -> buyer completes. Returns the gig id."""
    offered = _p2p(
        stack.gig_board, agent_id, "register.service",
        input={
            "name": service_name,
            "description": "cross-app service by %s" % agent_id,
            "capability_id": GIG_BOARD_CAP,
        },
        capability=GIG_BOARD_CAP,
    )
    assert offered.status_code == 200, offered.text
    service = offered.json()["result"]["service"]
    assert service["provider_principal"] == agent_id

    gig = requests.post(
        "%s/api/gigs" % stack.gig_board,
        json={
            "service_id": service["id"],
            "buyer_principal": buyer,
            "description": "hire %s" % agent_id,
        },
        timeout=TIMEOUT,
    )
    assert gig.status_code == 200, gig.text
    gig_id = gig.json()["gig"]["id"]

    done = requests.post(
        "%s/api/gigs/%s/complete" % (stack.gig_board, gig_id),
        json={"buyer_principal": buyer, "outcome": "well done"},
        timeout=TIMEOUT,
    )
    assert done.status_code == 200, done.text
    return gig_id


def _store_credential(vault_url, user_principal_id, name="api-key"):
    """Store a (fake ciphertext) credential; the Vault never inspects it."""
    resp = requests.post(
        "%s/credentials" % vault_url,
        json={
            "name": name,
            "credential_type": "api_key",
            "encrypted_data": "ZmFrZS1jaXBoZXJ0ZXh0",
            "nonce": "ZmFrZS1ub25jZQ==",
            "user_principal_id": user_principal_id,
        },
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["credential_id"]


def _vault_access(vault_url, credential_id, agent_principal_id):
    return requests.post(
        "%s/credentials/%s/access" % (vault_url, credential_id),
        json={"agent_principal_id": agent_principal_id},
        timeout=TIMEOUT,
    )


# ---------------------------------------------------------------------------
# The full-stack fixture: Registry + Vault + Agent Marketplace + both apps,
# all on ephemeral ports, all wired through the ONE Registry.
# ---------------------------------------------------------------------------


class FullStack(object):
    """URLs of every running service in one Phase B ecosystem."""

    def __init__(self, registry, vault, agent_marketplace, marketplace,
                 gig_board):
        self.registry = registry
        self.vault = vault
        self.agent_marketplace = agent_marketplace
        self.marketplace = marketplace
        self.gig_board = gig_board


@pytest.fixture
def stack():
    servers = []

    def spin(server):
        servers.append(server)
        _start(server)
        return _url(server)

    registry = spin(make_registry_server(port=0))
    vault = spin(make_vault_server(port=0))
    agent_marketplace = spin(
        make_agent_marketplace_server(
            port=0, registry_url=registry, vault_url=vault
        )
    )
    marketplace = spin(make_marketplace_server(port=0, registry_url=registry))
    gig_board = spin(make_gig_board_server(port=0, registry_url=registry))

    # Both apps + both shared services registered in the SAME Registry.
    _register_app(
        registry, "marketplace", marketplace,
        [MARKETPLACE_CAP, "p2p.ping"],
    )
    _register_app(
        registry, "gig-board", gig_board, [GIG_BOARD_CAP, "p2p.ping"]
    )
    _register_app(registry, "vault", vault, [], credential_vault=True)
    _register_app(
        registry, "agent-marketplace", agent_marketplace, [],
        agent_marketplace=True,
    )

    yield FullStack(registry, vault, agent_marketplace, marketplace, gig_board)

    for server in reversed(servers):
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# 1. One identity, two apps
# ---------------------------------------------------------------------------


class TestOneIdentityTwoApps:
    def test_agent_registered_once_works_and_is_visible_everywhere(
        self, stack
    ):
        _register_user(stack.registry, "user:author")
        _register_agent(stack.registry, "agent:a", [MARKETPLACE_CAP])

        # Registered ONCE, the agent completes a full marketplace cycle.
        _complete_marketplace_task_via_agent(
            stack, "agent:a", "user:author", "translate a document"
        )

        # Direct Registry view: the verified task is recorded.
        reputation = _agent_reputation(stack.registry, "agent:a")
        assert reputation["tasks_verified"] == 1
        assert reputation["verification_rate"] == 1.0

        # Both apps are registered against the SAME Registry, so their
        # registry connections are literally the same directory: assert the
        # shared Registry lists both apps...
        apps = requests.get(
            "%s/apps" % stack.registry, timeout=TIMEOUT
        ).json()["apps"]
        by_id = {a["app_id"]: a for a in apps}
        assert by_id["marketplace"]["app_endpoint"] == stack.marketplace
        assert by_id["gig-board"]["app_endpoint"] == stack.gig_board

        # ...and that a reputation query "as marketplace sees it" and "as
        # gig-board sees it" (each app's registry_url is this Registry)
        # return the identical record.
        marketplace_view = _agent_reputation(stack.registry, "agent:a")
        gig_board_view = _agent_reputation(stack.registry, "agent:a")
        assert marketplace_view == gig_board_view == reputation

        # The SAME identity operates in gig-board with no re-registration:
        # P2P permission passes and the agent can browse gig-board work.
        resp = _p2p(
            stack.gig_board, "agent:a", "list.work_opportunities",
            capability=GIG_BOARD_CAP,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["result"]["opportunities"] == []


# ---------------------------------------------------------------------------
# 2. Agent B works in gig-board
# ---------------------------------------------------------------------------


class TestGigBoardAgentWork:
    def test_agent_b_earns_gig_board_reputation(self, stack):
        _register_user(stack.registry, "user:buyer")
        _register_agent(stack.registry, "agent:b", [GIG_BOARD_CAP])

        _complete_gig_via_agent(
            stack, "agent:b", "user:buyer", service_name="pipe fixing"
        )

        reputation = _agent_reputation(stack.registry, "agent:b")
        assert reputation["tasks_verified"] == 1
        assert reputation["verification_rate"] == 1.0

        # The record is attributed to the gig-board capability (mirror the
        # principal into the user store to read the per-capability records;
        # see module docstring).
        _register_user(stack.registry, "agent:b")
        records = _reputation_records(stack.registry, "agent:b")
        assert len(records) == 1
        assert records[0]["capability_id"] == GIG_BOARD_CAP
        assert records[0]["tasks_verified"] == 1


# ---------------------------------------------------------------------------
# 3. Cross-capability isolation
# ---------------------------------------------------------------------------


class TestCrossCapabilityIsolation:
    def test_marketplace_reputation_does_not_bleed_into_gig_board(
        self, stack
    ):
        _register_user(stack.registry, "user:author")
        _register_agent(stack.registry, "agent:a", [MARKETPLACE_CAP])

        _complete_marketplace_task_via_agent(
            stack, "agent:a", "user:author", "summarize a paper"
        )

        # Per-capability records distinguish capability_id: agent A has a
        # marketplace.tasks record and NO gig-board.gigs record.
        _register_user(stack.registry, "agent:a")
        records = _reputation_records(stack.registry, "agent:a")
        by_capability = {r["capability_id"]: r for r in records}
        assert MARKETPLACE_CAP in by_capability
        assert GIG_BOARD_CAP not in by_capability
        assert by_capability[MARKETPLACE_CAP]["tasks_verified"] == 1

        # Another agent's gig-board work never touches agent A's record.
        _register_user(stack.registry, "user:buyer")
        _register_agent(stack.registry, "agent:other", [GIG_BOARD_CAP])
        _complete_gig_via_agent(stack, "agent:other", "user:buyer")

        records = _reputation_records(stack.registry, "agent:a")
        assert {r["capability_id"] for r in records} == {MARKETPLACE_CAP}
        assert _agent_reputation(
            stack.registry, "agent:a"
        )["tasks_verified"] == 1


# ---------------------------------------------------------------------------
# 4. Mixed history: one principal, reputation from BOTH apps
# ---------------------------------------------------------------------------


class TestMixedCrossAppHistory:
    def test_registry_aggregates_marketplace_and_gig_board_work(self, stack):
        _register_user(stack.registry, "user:author")
        _register_user(stack.registry, "user:buyer")
        _register_agent(stack.registry, "agent:a", [MARKETPLACE_CAP])

        # Work in the marketplace...
        _complete_marketplace_task_via_agent(
            stack, "agent:a", "user:author", "analyze a dataset"
        )
        # ...and ALSO offer + complete a gig in the gig board.
        _complete_gig_via_agent(
            stack, "agent:a", "user:buyer", service_name="data analysis"
        )

        # Aggregated: total verified = marketplace tasks + gigs.
        reputation = _agent_reputation(stack.registry, "agent:a")
        assert reputation["tasks_verified"] == 2
        assert reputation["tasks_rejected"] == 0
        assert reputation["verification_rate"] == 1.0

        # Per-capability records show BOTH apps under ONE principal.
        _register_user(stack.registry, "agent:a")
        records = _reputation_records(stack.registry, "agent:a")
        by_capability = {r["capability_id"]: r for r in records}
        assert set(by_capability) == {MARKETPLACE_CAP, GIG_BOARD_CAP}
        assert by_capability[MARKETPLACE_CAP]["tasks_verified"] == 1
        assert by_capability[GIG_BOARD_CAP]["tasks_verified"] == 1


# ---------------------------------------------------------------------------
# 5. Discovery chain: registry URL -> whole ecosystem -> direct P2P
# ---------------------------------------------------------------------------


class TestDiscoveryChain:
    def test_fresh_client_discovers_everything_then_reaches_marketplace(
        self, stack
    ):
        client = FederationClient(stack.registry)
        joined = client.join_ecosystem(
            "fresh-app",
            "http://127.0.0.1:1",  # never contacted; registration data only
            "http://127.0.0.1:1",
            ["fresh-app.things", "p2p.ping"],
        )

        # Knowing ONLY the registry URL, the newcomer sees both apps...
        discovered = {
            app["app_id"]: app for app in joined["ecosystem_apps"]
        }
        assert "marketplace" in discovered
        assert "gig-board" in discovered
        assert discovered["marketplace"]["p2p_endpoint"] == stack.marketplace
        assert discovered["gig-board"]["p2p_endpoint"] == stack.gig_board

        # ...the vault service, and the agent marketplace.
        assert joined["vault"] is not None
        assert joined["vault"]["endpoint"] == stack.vault
        assert joined["agent_marketplace"] is not None
        assert joined["agent_marketplace"]["endpoint"] == (
            stack.agent_marketplace
        )

        # The discovered endpoint is live: direct P2P ping to the
        # marketplace (requester must be a known principal).
        _register_user(stack.registry, "user:fresh")
        pong = _p2p(
            discovered["marketplace"]["p2p_endpoint"],
            "user:fresh", "ping", capability="p2p.ping",
        )
        assert pong.status_code == 200, pong.text
        assert pong.json()["result"] == {
            "pong": True, "app_id": "marketplace",
        }


# ---------------------------------------------------------------------------
# 6. Agent Marketplace search reflects cross-app work
# ---------------------------------------------------------------------------


class TestMarketplaceSearchReflectsCrossAppWork:
    def test_search_shows_reputation_from_both_apps(self, stack):
        _register_user(stack.registry, "user:author")
        _register_user(stack.registry, "user:buyer")
        _register_agent(stack.registry, "agent:a", [MARKETPLACE_CAP])

        _complete_marketplace_task_via_agent(
            stack, "agent:a", "user:author", "write a report"
        )
        _complete_gig_via_agent(stack, "agent:a", "user:buyer")

        client = AgentMarketplaceClient(stack.agent_marketplace)
        agents = client.search_agents(MARKETPLACE_CAP)
        assert [a["principal_id"] for a in agents] == ["agent:a"]
        # Aggregated tasks_verified includes work done in BOTH apps.
        assert agents[0]["reputation"]["tasks_verified"] == 2
        assert agents[0]["reputation"]["verification_rate"] == 1.0


# ---------------------------------------------------------------------------
# 7. Hiring + credential + work combo (full-stack U8 flow)
# ---------------------------------------------------------------------------


class TestHiringWithCredentials:
    def test_hire_grants_vault_access_and_revoke_removes_it(self, stack):
        _register_user(stack.registry, "user:author")
        _register_user(stack.registry, "user:alice")
        _register_agent(stack.registry, "agent:a", [MARKETPLACE_CAP])

        # The agent has real cross-app history before being hired.
        _complete_marketplace_task_via_agent(
            stack, "agent:a", "user:author", "cleanup a database"
        )

        credential_id = _store_credential(stack.vault, "user:alice")
        # Before hiring: no access.
        assert _vault_access(
            stack.vault, credential_id, "agent:a"
        ).status_code == 403

        client = AgentMarketplaceClient(stack.agent_marketplace)
        grant = client.hire_agent(
            agent_principal_id="agent:a",
            user_principal_id="user:alice",
            scoped_capabilities=[MARKETPLACE_CAP],
            credential_scopes=[
                {"credential_id": credential_id, "scope": "read"},
            ],
        )
        assert grant["status"] == "active"

        # The hire produced a real Vault grant.
        allowed = _vault_access(stack.vault, credential_id, "agent:a")
        assert allowed.status_code == 200, allowed.text
        body = allowed.json()
        assert body["access_granted"] is True
        assert body["scope"] == "read"

        # Revoking the hire revokes Vault access too.
        revoked = client.revoke_hiring(grant["grant_id"], "user:alice")
        assert revoked["grant"]["status"] == "revoked"
        assert _vault_access(
            stack.vault, credential_id, "agent:a"
        ).status_code == 403


# ---------------------------------------------------------------------------
# 8. Permission boundary
# ---------------------------------------------------------------------------


class TestPermissionBoundary:
    def test_unadvertised_capability_is_denied_with_reason(self, stack):
        _register_agent(stack.registry, "agent:limited", [MARKETPLACE_CAP])

        # The marketplace does NOT advertise gig-board.gigs: denied.
        resp = _p2p(
            stack.marketplace, "agent:limited", "list.work_opportunities",
            capability=GIG_BOARD_CAP,
        )
        assert resp.status_code == 403, resp.text
        body = resp.json()
        assert body["error"] == "permission denied"
        assert GIG_BOARD_CAP in body["reason"]
        assert "marketplace" in body["reason"]

        # A completely made-up capability is denied by the gig board too.
        resp = _p2p(
            stack.gig_board, "agent:limited", "list.work_opportunities",
            capability="no.such-capability",
        )
        assert resp.status_code == 403, resp.text
        assert "no.such-capability" in resp.json()["reason"]

        # Sanity: the same agent IS allowed for advertised capabilities.
        assert _p2p(
            stack.marketplace, "agent:limited", "list.work_opportunities",
            capability=MARKETPLACE_CAP,
        ).status_code == 200


# ---------------------------------------------------------------------------
# 9. Registry as single source of truth (three views, one truth)
# ---------------------------------------------------------------------------


class TestRegistrySingleSourceOfTruth:
    def test_three_views_agree_immediately_after_completion(self, stack):
        _register_user(stack.registry, "user:author")
        _register_agent(stack.registry, "agent:a", [MARKETPLACE_CAP])

        _complete_marketplace_task_via_agent(
            stack, "agent:a", "user:author", "one verified task"
        )

        # View 1: direct Registry query.
        registry_view = _agent_reputation(stack.registry, "agent:a")
        assert registry_view["tasks_verified"] == 1

        # View 2: agent-marketplace detail endpoint (live Registry pull).
        client = AgentMarketplaceClient(stack.agent_marketplace)
        detail = client.get_agent("agent:a")
        assert detail["reputation"] == registry_view
        assert detail["agent"]["principal_id"] == "agent:a"

        # View 3: agent-marketplace capability search.
        search = client.search_agents(MARKETPLACE_CAP)
        assert [a["principal_id"] for a in search] == ["agent:a"]
        assert search[0]["reputation"] == registry_view


# ---------------------------------------------------------------------------
# 10. Full autonomous cross-app cycle
# ---------------------------------------------------------------------------


class TestAutonomousCrossAppCycle:
    def test_single_cycle_agent_accumulates_history_from_both_apps(
        self, stack
    ):
        _register_user(stack.registry, "user:author")
        _register_user(stack.registry, "user:buyer")

        agent = MarketplaceCoordinatorAgent(
            registry_url=stack.registry,
            agent_id="agent:c",
            capability=MARKETPLACE_CAP,
        )
        assert agent.register() is True

        # Agent C ALSO offers a service in the gig board (same identity).
        coordinator = AgentCoordinator(stack.registry, "agent:c")
        service = coordinator.offer_service(
            "gig-board", "report writing", "fast, verified reports",
            capability_id=GIG_BOARD_CAP,
        )
        assert service["provider_principal"] == "agent:c"

        # Autonomous marketplace lifecycle via single_cycle().
        task = _create_task(stack.marketplace, "user:author", "cross-app job")
        first = agent.single_cycle()
        assert first["action"] == "bid_submitted"
        assert first["task_id"] == task["id"]

        bids = _get_bids(stack.marketplace, task["id"])
        assert _accept_bid(
            stack.marketplace, task["id"], bids[0]["bid_id"], "user:author"
        ).status_code == 200

        performed = agent.single_cycle()
        assert performed["action"] == "result_submitted"
        assert performed["task"]["work_result"]["submitted_by"] == "agent:c"

        assert _complete_task(
            stack.marketplace, task["id"], "user:author"
        ).status_code == 200
        finished = agent.single_cycle()
        assert finished["action"] == "task_completed"

        # Meanwhile a buyer hires Agent C's offered gig-board service.
        gig = requests.post(
            "%s/api/gigs" % stack.gig_board,
            json={
                "service_id": service["id"],
                "buyer_principal": "user:buyer",
                "description": "write my annual report",
            },
            timeout=TIMEOUT,
        )
        assert gig.status_code == 200, gig.text
        done = requests.post(
            "%s/api/gigs/%s/complete"
            % (stack.gig_board, gig.json()["gig"]["id"]),
            json={"buyer_principal": "user:buyer", "outcome": "delivered"},
            timeout=TIMEOUT,
        )
        assert done.status_code == 200, done.text

        # BOTH histories accumulate under one principal_id.
        reputation = _agent_reputation(stack.registry, "agent:c")
        assert reputation["tasks_verified"] == 2
        assert reputation["verification_rate"] == 1.0

        _register_user(stack.registry, "agent:c")
        records = _reputation_records(stack.registry, "agent:c")
        assert {r["capability_id"] for r in records} == {
            MARKETPLACE_CAP, GIG_BOARD_CAP,
        }
