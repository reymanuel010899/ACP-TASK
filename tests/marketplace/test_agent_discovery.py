"""Agent Marketplace discovery tests (Phase B, unit U8).

The agent marketplace is a standalone service that PULLS agent listings
live from the Registry (source of truth for agents + reputation) and
enriches them with locally-owned ratings.

All servers run on EPHEMERAL ports (port=0), never fixed ports.
"""

import socket
import threading

import pytest
import requests

from agent_marketplace.app import make_server as make_agent_marketplace_server
from registry.app import make_server as make_registry_server

TIMEOUT = 5.0


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
                    created_by="user:owner", name=None, pricing=None):
    agent_card = {
        "name": name or principal_id,
        "description": "test agent %s" % principal_id,
        "capabilities": capabilities,
    }
    if pricing is not None:
        agent_card["pricing"] = pricing
    resp = requests.post(
        "%s/agents/register" % registry_url,
        json={
            "principal_id": principal_id,
            "created_by": created_by,
            "agent_card": agent_card,
        },
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _record_reputation(registry_url, principal_id, capability_id, task_id,
                       verified):
    resp = requests.post(
        "%s/users/%s/reputation" % (registry_url, principal_id),
        json={
            "task_id": task_id,
            "verified": verified,
            "capability_id": capability_id,
        },
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _hire(marketplace_url, agent_principal_id, user_principal_id,
          scoped_capabilities):
    resp = requests.post(
        "%s/marketplace/hiring-grants" % marketplace_url,
        json={
            "agent_principal_id": agent_principal_id,
            "user_principal_id": user_principal_id,
            "scoped_capabilities": scoped_capabilities,
        },
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["grant"]


def _rate(marketplace_url, agent_principal_id, user_principal_id, rating,
          review_text=None):
    body = {
        "agent_principal_id": agent_principal_id,
        "user_principal_id": user_principal_id,
        "rating": rating,
    }
    if review_text is not None:
        body["review_text"] = review_text
    resp = requests.post(
        "%s/marketplace/ratings" % marketplace_url,
        json=body,
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Fixtures (ephemeral ports only)
# ---------------------------------------------------------------------------


@pytest.fixture
def registry():
    server = make_registry_server(port=0)
    _start(server)
    yield _url(server)
    server.shutdown()
    server.server_close()


@pytest.fixture
def agent_marketplace(registry):
    """Agent marketplace connected to the registry (no vault)."""
    server = make_agent_marketplace_server(port=0, registry_url=registry)
    _start(server)
    yield _url(server)
    server.shutdown()
    server.server_close()


@pytest.fixture
def dead_registry_url():
    """A URL nothing is listening on (bind an ephemeral port, then free it)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return "http://127.0.0.1:%d" % port


# ---------------------------------------------------------------------------
# 1-2. Capability search pulls live from the Registry
# ---------------------------------------------------------------------------


class TestCapabilitySearch:
    def test_search_returns_only_matching_capability(
        self, registry, agent_marketplace
    ):
        _register_user(registry, "user:owner")
        _register_agent(registry, "agent:translator", ["translation"])
        _register_agent(registry, "agent:coder", ["coding"])

        resp = requests.get(
            "%s/marketplace/agents" % agent_marketplace,
            params={"capability": "translation"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
        agents = resp.json()["agents"]
        assert len(agents) == 1
        assert agents[0]["principal_id"] == "agent:translator"
        # Enriched with local rating fields.
        assert agents[0]["rating_count"] == 0
        assert agents[0]["avg_rating"] is None

    def test_no_matching_agents_is_empty_list(
        self, registry, agent_marketplace
    ):
        _register_user(registry, "user:owner")
        _register_agent(registry, "agent:translator", ["translation"])

        resp = requests.get(
            "%s/marketplace/agents" % agent_marketplace,
            params={"capability": "no-such-capability"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["agents"] == []


# ---------------------------------------------------------------------------
# 3. min_reputation filtering (Registry reputation is the source of truth)
# ---------------------------------------------------------------------------


class TestMinReputationFilter:
    def test_min_reputation_excludes_fresh_agents(
        self, registry, agent_marketplace
    ):
        _register_user(registry, "user:owner")
        _register_agent(registry, "agent:proven", ["translation"])
        _register_agent(registry, "agent:fresh", ["translation"])

        # agent:proven earns verified-task reputation through the Registry.
        _record_reputation(
            registry, "agent:proven", "translation", "task-1", True
        )
        _record_reputation(
            registry, "agent:proven", "translation", "task-2", True
        )

        resp = requests.get(
            "%s/marketplace/agents" % agent_marketplace,
            params={"capability": "translation", "min_reputation": "0.5"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
        agents = resp.json()["agents"]
        assert [a["principal_id"] for a in agents] == ["agent:proven"]
        assert agents[0]["reputation"]["verification_rate"] == 1.0


# ---------------------------------------------------------------------------
# 4. Sorting by local avg_rating
# ---------------------------------------------------------------------------


class TestSorting:
    def test_higher_avg_rating_listed_first(
        self, registry, agent_marketplace
    ):
        _register_user(registry, "user:owner")
        _register_user(registry, "user:client")
        _register_agent(registry, "agent:meh", ["translation"])
        _register_agent(registry, "agent:great", ["translation"])

        # user:client hires both agents, then rates them differently.
        _hire(agent_marketplace, "agent:meh", "user:client", ["translation"])
        _hire(agent_marketplace, "agent:great", "user:client", ["translation"])
        _rate(agent_marketplace, "agent:meh", "user:client", 3)
        _rate(agent_marketplace, "agent:great", "user:client", 5)

        resp = requests.get(
            "%s/marketplace/agents" % agent_marketplace,
            params={"capability": "translation"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
        agents = resp.json()["agents"]
        assert [a["principal_id"] for a in agents] == [
            "agent:great", "agent:meh",
        ]
        assert agents[0]["avg_rating"] == 5.0
        assert agents[1]["avg_rating"] == 3.0


# ---------------------------------------------------------------------------
# 5. Agent detail merges Registry data with local ratings
# ---------------------------------------------------------------------------


class TestAgentDetail:
    def test_detail_merges_registry_reputation_and_local_ratings(
        self, registry, agent_marketplace
    ):
        _register_user(registry, "user:owner")
        _register_user(registry, "user:client")
        _register_agent(
            registry, "agent:star", ["translation"],
            pricing={"per_task": 5},
        )
        _record_reputation(
            registry, "agent:star", "translation", "task-1", True
        )
        _hire(agent_marketplace, "agent:star", "user:client", ["translation"])
        _rate(
            agent_marketplace, "agent:star", "user:client", 4,
            review_text="solid work",
        )

        resp = requests.get(
            "%s/marketplace/agents/%s" % (agent_marketplace, "agent:star"),
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        # Registry side.
        assert body["agent"]["principal_id"] == "agent:star"
        assert body["agent"]["agent_card"]["pricing"] == {"per_task": 5}
        assert body["reputation"]["tasks_verified"] == 1
        assert body["reputation"]["verification_rate"] == 1.0

        # Local marketplace side.
        assert body["avg_rating"] == 4.0
        assert body["rating_count"] == 1
        assert body["active_hirings"] == 1
        assert len(body["reviews"]) == 1
        assert body["reviews"][0]["rating"] == 4
        assert body["reviews"][0]["review_text"] == "solid work"
        assert body["reviews"][0]["user_principal_id"] == "user:client"


# ---------------------------------------------------------------------------
# 6-7. Failure modes
# ---------------------------------------------------------------------------


class TestFailureModes:
    def test_registry_unreachable_is_502(self, dead_registry_url):
        server = make_agent_marketplace_server(
            port=0, registry_url=dead_registry_url
        )
        _start(server)
        try:
            resp = requests.get(
                "%s/marketplace/agents" % _url(server),
                params={"capability": "translation"},
                timeout=TIMEOUT,
            )
            assert resp.status_code == 502, resp.text
            assert resp.json()["error"]
        finally:
            server.shutdown()
            server.server_close()

    def test_unknown_agent_detail_is_404(self, registry, agent_marketplace):
        resp = requests.get(
            "%s/marketplace/agents/%s"
            % (agent_marketplace, "agent:does-not-exist"),
            timeout=TIMEOUT,
        )
        assert resp.status_code == 404, resp.text
