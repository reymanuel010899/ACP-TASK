"""Shared agent work-coordination library (Phase B, U10).

Built on :class:`libs.p2p_client.P2PClient`: an agent Principal discovers
work opportunities in federated apps, submits bids, polls its bid status,
delivers work results, and offers services — all over the direct P2P layer
(RFC-0003). The Registry is only used for endpoint discovery; every work
request goes straight to the target app.

Usage::

    from libs.agent_coordination import AgentCoordinator

    coordinator = AgentCoordinator(
        "http://127.0.0.1:8090", "agent:helper"
    )
    opportunities = coordinator.discover_work("marketplace")
    bid = coordinator.submit_bid(
        "marketplace", opportunities[0]["id"], "done today for 2 credits"
    )
    status = coordinator.check_bid_status(
        "marketplace", opportunities[0]["id"]
    )
    if status["my_bid"]["status"] == "accepted":
        coordinator.submit_result(
            "marketplace", opportunities[0]["id"], "work is done"
        )

The agent must be registered in the Registry (``POST /agents/register``,
U5) or every call fails the target app's permission check
(:class:`libs.p2p_client.P2PPermissionDenied`).
"""

from typing import Optional

from libs.p2p_client import DEFAULT_TIMEOUT, P2PClient, P2PError


class AgentCoordinationError(P2PError):
    """A coordination call could not be completed."""


class AgentCoordinator(object):
    """High-level work coordination for one agent Principal."""

    def __init__(self, registry_url, agent_principal_id,
                 timeout=DEFAULT_TIMEOUT, session=None):
        # type: (str, str, float, object) -> None
        if not agent_principal_id:
            raise ValueError("agent_principal_id is required")
        self.agent_principal_id = agent_principal_id
        # When a session (libs.session.SessionContext) is supplied the
        # underlying P2P client signs every work request, so apps enforcing
        # ``require_signatures`` (U18) accept the agent's bids/results. The
        # session's principal_id MUST equal ``agent_principal_id`` or the app
        # rejects the identity mismatch (403).
        self.client = P2PClient(registry_url, timeout=timeout, session=session)
        # app_id -> default work capability (first non-ping capability).
        self._capability_cache = {}  # type: dict

    # -- capabilities ---------------------------------------------------------

    def _work_capability(self, app_id, capability_id=None):
        # type: (str, Optional[str]) -> str
        """The capability_id to stamp on the P2P envelope: the caller's
        explicit choice, or the app's first advertised non-ping capability
        (discovered once per app, then cached)."""
        if capability_id:
            return capability_id
        if app_id not in self._capability_cache:
            app = self.client.discover_app(app_id)
            capabilities = [
                c
                for c in app.get("capabilities", [])
                if isinstance(c, str) and c and c != "p2p.ping"
            ]
            if not capabilities:
                raise AgentCoordinationError(
                    "app '%s' advertises no work capabilities" % app_id
                )
            self._capability_cache[app_id] = capabilities[0]
        return self._capability_cache[app_id]

    def _request(self, app_id, request_type, input, capability_id=None):  # noqa: A002
        # type: (str, str, dict, Optional[str]) -> dict
        response = self.client.p2p_request(
            target_app_id=app_id,
            requester_principal_id=self.agent_principal_id,
            request_type=request_type,
            capability_id=self._work_capability(app_id, capability_id),
            input=input,
        )
        result = response.get("result")
        if not isinstance(result, dict):
            raise AgentCoordinationError(
                "app '%s' returned a malformed '%s' response"
                % (app_id, request_type)
            )
        return result

    # -- work coordination ----------------------------------------------------

    def discover_work(self, app_id, capability_id=None):
        # type: (str, Optional[str]) -> list
        """Open work opportunities in ``app_id``, optionally filtered by
        capability (marketplace: open tasks; gig-board: offered services)."""
        p2p_input = {}
        if capability_id:
            p2p_input["capability_id"] = capability_id
        result = self._request(
            app_id, "list.work_opportunities", p2p_input, capability_id
        )
        opportunities = result.get("opportunities")
        return opportunities if isinstance(opportunities, list) else []

    def submit_bid(self, app_id, task_id, proposed_terms,
                   agent_reputation_note=None):
        # type: (str, str, str, Optional[str]) -> dict
        """Bid on an open task; re-bidding replaces this agent's pending
        bid. Returns the created bid."""
        p2p_input = {"task_id": task_id, "proposed_terms": proposed_terms}
        if agent_reputation_note is not None:
            p2p_input["agent_reputation_note"] = agent_reputation_note
        result = self._request(app_id, "submit.work_bid", p2p_input)
        bid = result.get("bid")
        if not isinstance(bid, dict):
            raise AgentCoordinationError(
                "app '%s' returned no bid for task '%s'" % (app_id, task_id)
            )
        return bid

    def check_bid_status(self, app_id, task_id):
        # type: (str, str) -> dict
        """The task's current state plus this agent's own bid:
        ``{"task": {...}, "my_bid": {...} | None}``."""
        result = self._request(
            app_id, "get.task_status", {"task_id": task_id}
        )
        if not isinstance(result.get("task"), dict):
            raise AgentCoordinationError(
                "app '%s' returned no task for '%s'" % (app_id, task_id)
            )
        return {"task": result["task"], "my_bid": result.get("my_bid")}

    def submit_result(self, app_id, task_id, result_summary, evidence=None):
        # type: (str, str, str, Optional[dict]) -> dict
        """Deliver the finished work for an accepted task; returns the
        updated (now 'delivered') task."""
        p2p_input = {"task_id": task_id, "result_summary": result_summary}
        if evidence is not None:
            p2p_input["evidence"] = evidence
        result = self._request(app_id, "submit.work_result", p2p_input)
        task = result.get("task")
        if not isinstance(task, dict):
            raise AgentCoordinationError(
                "app '%s' returned no task for '%s'" % (app_id, task_id)
            )
        return task

    def offer_service(self, app_id, name, description, capability_id=None,
                      pricing=None):
        # type: (str, str, str, Optional[str], Optional[object]) -> dict
        """Register this agent as a service provider (gig-board style
        apps); returns the created service record."""
        p2p_input = {"name": name, "description": description}
        if capability_id is not None:
            p2p_input["capability_id"] = capability_id
        if pricing is not None:
            p2p_input["pricing"] = pricing
        result = self._request(
            app_id, "register.service", p2p_input, capability_id
        )
        service = result.get("service")
        if not isinstance(service, dict):
            raise AgentCoordinationError(
                "app '%s' returned no service record" % app_id
            )
        return service
