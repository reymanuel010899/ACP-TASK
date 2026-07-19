"""Integration tests for autonomous agent work coordination (Phase B, U10).

End-to-end over the P2P layer (RFC-0003): agents discover open work in apps,
submit bids, users accept a bid, the agent performs and submits the work, the
user approves completion, and the agent's reputation updates in the Registry.

All servers run on EPHEMERAL ports (port=0), never fixed ports. Agents are
registered in the Registry first so P2P permission checks pass.
"""

import threading

import pytest
import requests

from agents.marketplace_coordinator.agent import MarketplaceCoordinatorAgent
from apps.gig_board.server.app import make_server as make_gig_board_server
from apps.marketplace.server.app import make_server as make_marketplace_server
from libs.agent_coordination import AgentCoordinator
from registry.app import make_server as make_registry_server

TIMEOUT = 5.0
MARKETPLACE_CAP = "marketplace.tasks"
GIG_BOARD_CAP = "gig-board.gigs"


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
                "description": "autonomous work agent",
                "capabilities": capabilities,
            },
        },
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _register_app(registry_url, app_id, endpoint, capabilities):
    resp = requests.post(
        "%s/apps/register" % registry_url,
        json={
            "app_id": app_id,
            "app_endpoint": endpoint,
            "p2p_endpoint": endpoint,
            "capabilities": capabilities,
        },
        timeout=TIMEOUT,
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


def _agent_reputation(registry_url, agent_principal_id):
    resp = requests.get(
        "%s/agents/%s" % (registry_url, agent_principal_id), timeout=TIMEOUT
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["reputation"]


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
def marketplace(registry):
    """Marketplace connected to (and registered with) the registry."""
    server = make_marketplace_server(port=0, registry_url=registry)
    _start(server)
    url = _url(server)
    _register_app(registry, "marketplace", url, ["marketplace.tasks", "p2p.ping"])
    yield url
    server.shutdown()
    server.server_close()


@pytest.fixture
def gig_board(registry):
    """Gig board connected to (and registered with) the registry."""
    server = make_gig_board_server(port=0, registry_url=registry)
    _start(server)
    url = _url(server)
    _register_app(registry, "gig-board", url, ["gig-board.gigs", "p2p.ping"])
    yield url
    server.shutdown()
    server.server_close()


# ---------------------------------------------------------------------------
# 1. Work discovery
# ---------------------------------------------------------------------------


class TestWorkDiscovery:
    def test_agent_discovers_open_task(self, registry, marketplace):
        _register_user(registry, "user:author")
        _register_agent(registry, "agent:scout", [MARKETPLACE_CAP])
        task = _create_task(marketplace, "user:author", "translate a doc")

        resp = _p2p(marketplace, "agent:scout", "list.work_opportunities")
        assert resp.status_code == 200, resp.text
        opportunities = resp.json()["result"]["opportunities"]
        assert len(opportunities) == 1
        opp = opportunities[0]
        assert opp["id"] == task["id"]
        assert opp["description"] == "translate a doc"
        assert opp["author_principal"] == "user:author"
        assert opp["created_at"]

    def test_capability_filter_works(self, registry, marketplace):
        _register_user(registry, "user:author")
        _register_agent(registry, "agent:scout", [MARKETPLACE_CAP])
        _create_task(marketplace, "user:author", "translate a doc")

        # Matching filter -> the task shows up.
        resp = _p2p(
            marketplace, "agent:scout", "list.work_opportunities",
            input={"capability_id": MARKETPLACE_CAP},
        )
        assert resp.status_code == 200, resp.text
        assert len(resp.json()["result"]["opportunities"]) == 1

        # Non-matching filter -> empty.
        resp = _p2p(
            marketplace, "agent:scout", "list.work_opportunities",
            input={"capability_id": "some.other-capability"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["result"]["opportunities"] == []

    def test_non_open_tasks_are_not_listed(self, registry, marketplace):
        _register_user(registry, "user:author")
        _register_user(registry, "user:worker")
        _register_agent(registry, "agent:scout", [MARKETPLACE_CAP])
        task = _create_task(marketplace, "user:author", "walk my dog")
        resp = requests.post(
            "%s/api/tasks/%s/accept" % (marketplace, task["id"]),
            json={"worker_principal": "user:worker"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text

        resp = _p2p(marketplace, "agent:scout", "list.work_opportunities")
        assert resp.status_code == 200
        assert resp.json()["result"]["opportunities"] == []


# ---------------------------------------------------------------------------
# 2-4. Bidding
# ---------------------------------------------------------------------------


class TestBidding:
    def test_agent_bid_visible_to_author(self, registry, marketplace):
        _register_user(registry, "user:author")
        _register_agent(registry, "agent:worker", [MARKETPLACE_CAP])
        task = _create_task(marketplace, "user:author", "summarize a paper")

        resp = _p2p(
            marketplace, "agent:worker", "submit.work_bid",
            input={
                "task_id": task["id"],
                "proposed_terms": "done in 1 hour for 5 credits",
            },
        )
        assert resp.status_code == 200, resp.text
        bid = resp.json()["result"]["bid"]
        assert bid["task_id"] == task["id"]
        assert bid["agent_principal_id"] == "agent:worker"
        assert bid["proposed_terms"] == "done in 1 hour for 5 credits"
        assert bid["status"] == "pending"
        assert bid["bid_id"]
        assert bid["created_at"]

        bids = _get_bids(marketplace, task["id"])
        assert len(bids) == 1
        assert bids[0]["bid_id"] == bid["bid_id"]

    def test_second_bid_from_same_agent_replaces_pending(
        self, registry, marketplace
    ):
        _register_user(registry, "user:author")
        _register_agent(registry, "agent:worker", [MARKETPLACE_CAP])
        task = _create_task(marketplace, "user:author", "summarize a paper")

        first = _p2p(
            marketplace, "agent:worker", "submit.work_bid",
            input={"task_id": task["id"], "proposed_terms": "10 credits"},
        )
        assert first.status_code == 200
        second = _p2p(
            marketplace, "agent:worker", "submit.work_bid",
            input={"task_id": task["id"], "proposed_terms": "8 credits"},
        )
        assert second.status_code == 200, second.text

        bids = _get_bids(marketplace, task["id"])
        assert len(bids) == 1
        assert bids[0]["proposed_terms"] == "8 credits"
        assert bids[0]["status"] == "pending"

    def test_bid_on_non_open_task_is_400(self, registry, marketplace):
        _register_user(registry, "user:author")
        _register_user(registry, "user:worker")
        _register_agent(registry, "agent:worker", [MARKETPLACE_CAP])
        task = _create_task(marketplace, "user:author", "mow the lawn")
        resp = requests.post(
            "%s/api/tasks/%s/accept" % (marketplace, task["id"]),
            json={"worker_principal": "user:worker"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200

        resp = _p2p(
            marketplace, "agent:worker", "submit.work_bid",
            input={"task_id": task["id"], "proposed_terms": "cheap"},
        )
        assert resp.status_code == 400, resp.text

    def test_bid_on_unknown_task_is_404(self, registry, marketplace):
        _register_agent(registry, "agent:worker", [MARKETPLACE_CAP])
        resp = _p2p(
            marketplace, "agent:worker", "submit.work_bid",
            input={"task_id": "no-such-task", "proposed_terms": "cheap"},
        )
        assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# 5. Bid acceptance
# ---------------------------------------------------------------------------


class TestBidAcceptance:
    def test_author_accepts_bid_others_rejected(self, registry, marketplace):
        _register_user(registry, "user:author")
        _register_agent(registry, "agent:one", [MARKETPLACE_CAP])
        _register_agent(registry, "agent:two", [MARKETPLACE_CAP])
        task = _create_task(marketplace, "user:author", "build a website")

        bid_one = _p2p(
            marketplace, "agent:one", "submit.work_bid",
            input={"task_id": task["id"], "proposed_terms": "fast"},
        ).json()["result"]["bid"]
        _p2p(
            marketplace, "agent:two", "submit.work_bid",
            input={"task_id": task["id"], "proposed_terms": "cheap"},
        )

        # A non-author cannot accept.
        denied = _accept_bid(
            marketplace, task["id"], bid_one["bid_id"], "user:not-the-author"
        )
        assert denied.status_code == 403, denied.text

        accepted = _accept_bid(
            marketplace, task["id"], bid_one["bid_id"], "user:author"
        )
        assert accepted.status_code == 200, accepted.text
        body = accepted.json()
        assert body["task"]["status"] == "accepted"
        assert body["task"]["worker_principal"] == "agent:one"
        assert body["bid"]["status"] == "accepted"

        statuses = {
            b["agent_principal_id"]: b["status"]
            for b in _get_bids(marketplace, task["id"])
        }
        assert statuses == {"agent:one": "accepted", "agent:two": "rejected"}

    def test_accept_bid_on_non_open_task_is_400(self, registry, marketplace):
        _register_user(registry, "user:author")
        _register_agent(registry, "agent:one", [MARKETPLACE_CAP])
        task = _create_task(marketplace, "user:author", "paint a fence")
        bid = _p2p(
            marketplace, "agent:one", "submit.work_bid",
            input={"task_id": task["id"], "proposed_terms": "ok"},
        ).json()["result"]["bid"]
        assert _accept_bid(
            marketplace, task["id"], bid["bid_id"], "user:author"
        ).status_code == 200

        again = _accept_bid(
            marketplace, task["id"], bid["bid_id"], "user:author"
        )
        assert again.status_code == 400, again.text


# ---------------------------------------------------------------------------
# 6. Work result submission
# ---------------------------------------------------------------------------


class TestWorkResultSubmission:
    def _accepted_task(self, registry, marketplace):
        _register_user(registry, "user:author")
        _register_agent(registry, "agent:winner", [MARKETPLACE_CAP])
        _register_agent(registry, "agent:loser", [MARKETPLACE_CAP])
        task = _create_task(marketplace, "user:author", "write a report")
        bid = _p2p(
            marketplace, "agent:winner", "submit.work_bid",
            input={"task_id": task["id"], "proposed_terms": "by tomorrow"},
        ).json()["result"]["bid"]
        assert _accept_bid(
            marketplace, task["id"], bid["bid_id"], "user:author"
        ).status_code == 200
        return task

    def test_accepted_agent_submits_result(self, registry, marketplace):
        task = self._accepted_task(registry, marketplace)

        resp = _p2p(
            marketplace, "agent:winner", "submit.work_result",
            input={
                "task_id": task["id"],
                "result_summary": "report written, 10 pages",
                "evidence": {"word_count": 4200},
            },
        )
        assert resp.status_code == 200, resp.text
        delivered = resp.json()["result"]["task"]
        assert delivered["status"] == "delivered"
        assert delivered["work_result"]["result_summary"] == (
            "report written, 10 pages"
        )
        assert delivered["work_result"]["evidence"] == {"word_count": 4200}
        assert delivered["work_result"]["submitted_by"] == "agent:winner"

    def test_non_accepted_agent_submit_is_403(self, registry, marketplace):
        task = self._accepted_task(registry, marketplace)
        resp = _p2p(
            marketplace, "agent:loser", "submit.work_result",
            input={"task_id": task["id"], "result_summary": "I did it too"},
        )
        assert resp.status_code == 403, resp.text

    def test_submit_result_on_open_task_is_400(self, registry, marketplace):
        _register_user(registry, "user:author")
        _register_agent(registry, "agent:eager", [MARKETPLACE_CAP])
        task = _create_task(marketplace, "user:author", "still open task")
        resp = _p2p(
            marketplace, "agent:eager", "submit.work_result",
            input={"task_id": task["id"], "result_summary": "done already"},
        )
        assert resp.status_code == 400, resp.text


# ---------------------------------------------------------------------------
# 7. Completion -> agent reputation in the Registry
# ---------------------------------------------------------------------------


class TestCompletionUpdatesAgentReputation:
    def test_author_completes_delivered_task(self, registry, marketplace):
        _register_user(registry, "user:author")
        _register_agent(registry, "agent:pro", [MARKETPLACE_CAP])
        before = _agent_reputation(registry, "agent:pro")
        assert before["tasks_verified"] == 0

        task = _create_task(marketplace, "user:author", "analyze a dataset")
        bid = _p2p(
            marketplace, "agent:pro", "submit.work_bid",
            input={"task_id": task["id"], "proposed_terms": "2 credits"},
        ).json()["result"]["bid"]
        assert _accept_bid(
            marketplace, task["id"], bid["bid_id"], "user:author"
        ).status_code == 200
        assert _p2p(
            marketplace, "agent:pro", "submit.work_result",
            input={"task_id": task["id"], "result_summary": "analysis done"},
        ).status_code == 200

        resp = _complete_task(marketplace, task["id"], "user:author")
        assert resp.status_code == 200, resp.text
        assert resp.json()["task"]["status"] == "completed"

        after = _agent_reputation(registry, "agent:pro")
        assert after["tasks_verified"] == 1
        assert after["verification_rate"] == 1.0


# ---------------------------------------------------------------------------
# 8. Unknown agent principal -> P2P permission denied
# ---------------------------------------------------------------------------


class TestUnknownAgentDenied:
    def test_unregistered_agent_bid_is_403(self, registry, marketplace):
        _register_user(registry, "user:author")
        task = _create_task(marketplace, "user:author", "tempting task")

        resp = _p2p(
            marketplace, "agent:ghost", "submit.work_bid",
            input={"task_id": task["id"], "proposed_terms": "trust me"},
        )
        assert resp.status_code == 403, resp.text
        body = resp.json()
        assert body["error"]
        assert body["reason"]
        assert _get_bids(marketplace, task["id"]) == []


# ---------------------------------------------------------------------------
# 9. Gig board: agents offer services, buyers hire, reputation updates
# ---------------------------------------------------------------------------


class TestGigBoardAgentServices:
    def test_agent_offers_service_and_earns_reputation(
        self, registry, gig_board
    ):
        _register_user(registry, "user:buyer")
        _register_agent(registry, "agent:plumber", [GIG_BOARD_CAP])

        coordinator = AgentCoordinator(registry, "agent:plumber")
        service = coordinator.offer_service(
            "gig-board", "pipe fixing", "I fix leaky pipes fast",
            capability_id=GIG_BOARD_CAP,
        )
        assert service["provider_principal"] == "agent:plumber"
        assert service["capability_id"] == GIG_BOARD_CAP

        # The service is discoverable as a work opportunity over P2P.
        resp = _p2p(
            gig_board, "agent:plumber", "list.work_opportunities",
            capability=GIG_BOARD_CAP,
        )
        assert resp.status_code == 200, resp.text
        opportunities = resp.json()["result"]["opportunities"]
        assert any(o["id"] == service["id"] for o in opportunities)
        offered = [o for o in opportunities if o["id"] == service["id"]][0]
        assert offered["provider_principal"] == "agent:plumber"

        # Buyer hires and completes the gig through the normal flow.
        gig = requests.post(
            "%s/api/gigs" % gig_board,
            json={
                "service_id": service["id"],
                "buyer_principal": "user:buyer",
                "description": "fix my kitchen sink",
            },
            timeout=TIMEOUT,
        )
        assert gig.status_code == 200, gig.text
        gig_id = gig.json()["gig"]["id"]

        done = requests.post(
            "%s/api/gigs/%s/complete" % (gig_board, gig_id),
            json={"buyer_principal": "user:buyer", "outcome": "sink fixed"},
            timeout=TIMEOUT,
        )
        assert done.status_code == 200, done.text

        reputation = _agent_reputation(registry, "agent:plumber")
        assert reputation["tasks_verified"] == 1

    def test_unregistered_agent_cannot_offer_service(
        self, registry, gig_board
    ):
        resp = _p2p(
            gig_board, "agent:phantom", "register.service",
            input={"name": "scam", "description": "totally legit"},
            capability=GIG_BOARD_CAP,
        )
        assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# 10. AgentCoordinator + example autonomous agent, end to end
# ---------------------------------------------------------------------------


class TestAutonomousAgentEndToEnd:
    def test_single_cycle_agent_full_lifecycle(self, registry, marketplace):
        _register_user(registry, "user:author")

        agent = MarketplaceCoordinatorAgent(
            registry_url=registry,
            agent_id="agent:auto-1",
            capability=MARKETPLACE_CAP,
        )
        assert agent.register() is True
        # Registering twice is idempotent (409 treated as already-registered).
        assert agent.register() is True

        # Nothing to do yet.
        idle = agent.single_cycle()
        assert idle["action"] == "idle"

        task = _create_task(marketplace, "user:author", "autonomous work")

        # Cycle 1: discover + bid.
        first = agent.single_cycle()
        assert first["action"] == "bid_submitted"
        assert first["task_id"] == task["id"]
        bids = _get_bids(marketplace, task["id"])
        assert len(bids) == 1
        assert bids[0]["agent_principal_id"] == "agent:auto-1"

        # Cycle 2 before acceptance: agent keeps waiting.
        waiting = agent.single_cycle()
        assert waiting["action"] == "awaiting_acceptance"

        # Author accepts the agent's bid.
        assert _accept_bid(
            marketplace, task["id"], bids[0]["bid_id"], "user:author"
        ).status_code == 200

        # Cycle 3: agent notices acceptance, performs work, submits result.
        performed = agent.single_cycle()
        assert performed["action"] == "result_submitted"
        assert performed["task"]["status"] == "delivered"
        assert performed["task"]["work_result"]["submitted_by"] == (
            "agent:auto-1"
        )

        # Author approves completion -> reputation recorded in the Registry.
        resp = _complete_task(marketplace, task["id"], "user:author")
        assert resp.status_code == 200, resp.text

        reputation = _agent_reputation(registry, "agent:auto-1")
        assert reputation["tasks_verified"] == 1

        # Cycle 4: agent sees completion and goes back to idle state.
        finished = agent.single_cycle()
        assert finished["action"] == "task_completed"
        assert agent.active_task_id is None

    def test_coordinator_check_bid_status(self, registry, marketplace):
        _register_user(registry, "user:author")
        _register_agent(registry, "agent:direct", [MARKETPLACE_CAP])
        task = _create_task(marketplace, "user:author", "check my status")

        coordinator = AgentCoordinator(registry, "agent:direct")
        opportunities = coordinator.discover_work("marketplace")
        assert [o["id"] for o in opportunities] == [task["id"]]

        bid = coordinator.submit_bid(
            "marketplace", task["id"], "1 credit, done today"
        )
        assert bid["status"] == "pending"

        status = coordinator.check_bid_status("marketplace", task["id"])
        assert status["task"]["id"] == task["id"]
        assert status["my_bid"]["bid_id"] == bid["bid_id"]
        assert status["my_bid"]["status"] == "pending"


# ---------------------------------------------------------------------------
# 11. Existing human flows unaffected
# ---------------------------------------------------------------------------


class TestHumanFlowsUnaffected:
    def test_human_worker_accept_and_complete_still_works(
        self, registry, marketplace
    ):
        _register_user(registry, "user:author")
        _register_user(registry, "user:human-worker")
        task = _create_task(marketplace, "user:author", "human task")

        resp = requests.post(
            "%s/api/tasks/%s/accept" % (marketplace, task["id"]),
            json={"worker_principal": "user:human-worker"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["task"]["status"] == "accepted"

        # An accepted (not delivered) task can still be completed directly.
        done = _complete_task(marketplace, task["id"], "user:author")
        assert done.status_code == 200, done.text
        assert done.json()["task"]["status"] == "completed"

        user = requests.get(
            "%s/users/%s" % (registry, "user:human-worker"), timeout=TIMEOUT
        )
        assert user.status_code == 200
        records = user.json()["reputation_records"]
        assert records and records[0]["tasks_verified"] == 1
