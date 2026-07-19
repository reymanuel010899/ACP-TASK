"""Example autonomous marketplace work agent (Phase B, U10).

A minimal agent that coordinates work end-to-end over the P2P layer using
:class:`libs.agent_coordination.AgentCoordinator`:

1. registers itself in the Registry as an agent Principal (U5),
2. discovers open work in the marketplace (``list.work_opportunities``),
3. bids on the first matching open task (``submit.work_bid``),
4. polls until the author accepts its bid (``get.task_status``),
5. "performs" the work (a canned result for this demo agent) and submits
   it (``submit.work_result``),
6. and when the author approves completion, its reputation updates in the
   Registry through the marketplace's normal completion flow.

The lifecycle is driven one step at a time by :meth:`single_cycle` — tests
call it directly (no infinite loop); ``main()`` just calls it repeatedly.

Run: ``python -m agents.marketplace_coordinator.agent
--registry-url URL --agent-id agent:my-worker
[--capability marketplace.tasks] [--interval 2.0] [--max-cycles 0]``
"""

import argparse
import time

import requests

from libs.agent_coordination import AgentCoordinator

DEFAULT_CAPABILITY = "marketplace.tasks"
DEFAULT_TARGET_APP = "marketplace"
DEFAULT_HTTP_TIMEOUT = 5.0


class MarketplaceCoordinatorAgent(object):
    """One autonomous worker agent for one target app."""

    def __init__(
        self,
        registry_url,
        agent_id,
        capability=DEFAULT_CAPABILITY,
        target_app_id=DEFAULT_TARGET_APP,
        created_by="user:agent-operator",
        proposed_terms=None,
        http_timeout=DEFAULT_HTTP_TIMEOUT,
    ):
        # type: (str, str, str, str, str, str, float) -> None
        if not registry_url:
            raise ValueError("registry_url is required")
        if not agent_id:
            raise ValueError("agent_id is required")
        self.registry_url = registry_url.rstrip("/")
        self.agent_id = agent_id
        self.capability = capability
        self.target_app_id = target_app_id
        self.created_by = created_by
        self.proposed_terms = proposed_terms or (
            "autonomous completion by %s" % agent_id
        )
        self.http_timeout = http_timeout
        self.coordinator = AgentCoordinator(
            self.registry_url, agent_id, timeout=http_timeout
        )
        # The one task this agent is currently pursuing (bid placed).
        self.active_task_id = None  # type: str

    # -- registry registration (U5) --------------------------------------------

    def register(self):
        # type: () -> bool
        """Register this agent as a Principal in the Registry. Idempotent:
        an already-registered agent (409) counts as success."""
        try:
            resp = requests.post(
                "%s/agents/register" % self.registry_url,
                json={
                    "principal_id": self.agent_id,
                    "created_by": self.created_by,
                    "agent_card": {
                        "name": self.agent_id,
                        "description": "autonomous marketplace work agent "
                        "(U10 demo)",
                        "capabilities": [self.capability],
                    },
                },
                timeout=self.http_timeout,
            )
        except requests.RequestException:
            return False
        return resp.status_code in (200, 409)

    # -- the "work" -------------------------------------------------------------

    def perform_work(self, task):
        # type: (dict) -> dict
        """Produce the (canned, for this demo agent) work product."""
        summary = "completed '%s' autonomously" % task.get(
            "description", task.get("id", "task")
        )
        evidence = {
            "agent": self.agent_id,
            "method": "canned-demo-work",
            "task_id": task.get("id"),
        }
        return {"result_summary": summary, "evidence": evidence}

    # -- lifecycle -------------------------------------------------------------

    def single_cycle(self):
        # type: () -> dict
        """Advance the agent's work lifecycle by exactly one step.

        Returns ``{"action": ..., ...}`` describing what happened:
        ``idle`` (no open work), ``bid_submitted``,
        ``awaiting_acceptance``, ``result_submitted``,
        ``awaiting_completion``, ``task_completed``, or ``bid_lost``.
        """
        if self.active_task_id is None:
            return self._discover_and_bid()
        return self._advance_active_task()

    def _discover_and_bid(self):
        # type: () -> dict
        opportunities = self.coordinator.discover_work(
            self.target_app_id, capability_id=self.capability
        )
        for opportunity in opportunities:
            if opportunity.get("author_principal") == self.agent_id:
                continue  # never bid on our own postings
            bid = self.coordinator.submit_bid(
                self.target_app_id,
                opportunity["id"],
                self.proposed_terms,
            )
            self.active_task_id = opportunity["id"]
            return {
                "action": "bid_submitted",
                "task_id": opportunity["id"],
                "bid": bid,
            }
        return {"action": "idle"}

    def _advance_active_task(self):
        # type: () -> dict
        task_id = self.active_task_id
        status = self.coordinator.check_bid_status(
            self.target_app_id, task_id
        )
        task = status["task"]
        task_status = task.get("status")

        if task_status == "open":
            return {"action": "awaiting_acceptance", "task_id": task_id}

        if task_status == "accepted":
            if task.get("worker_principal") == self.agent_id:
                work = self.perform_work(task)
                delivered = self.coordinator.submit_result(
                    self.target_app_id,
                    task_id,
                    work["result_summary"],
                    evidence=work["evidence"],
                )
                return {
                    "action": "result_submitted",
                    "task_id": task_id,
                    "task": delivered,
                }
            # Someone else won the task; move on.
            self.active_task_id = None
            return {"action": "bid_lost", "task_id": task_id}

        if task_status == "delivered":
            return {"action": "awaiting_completion", "task_id": task_id}

        if task_status == "completed":
            self.active_task_id = None
            return {"action": "task_completed", "task_id": task_id}

        # Unknown state: forget the task rather than spinning on it.
        self.active_task_id = None
        return {
            "action": "task_abandoned",
            "task_id": task_id,
            "task_status": task_status,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="AgentTrust autonomous marketplace work agent (U10)"
    )
    parser.add_argument(
        "--registry-url", required=True,
        help="Registry base URL (agent registration + P2P discovery).",
    )
    parser.add_argument(
        "--agent-id", required=True,
        help="Agent principal_id, e.g. agent:my-worker.",
    )
    parser.add_argument(
        "--capability", default=DEFAULT_CAPABILITY,
        help="Work capability to pursue (default: %s)." % DEFAULT_CAPABILITY,
    )
    parser.add_argument(
        "--target-app", default=DEFAULT_TARGET_APP,
        help="Target app_id to work in (default: %s)." % DEFAULT_TARGET_APP,
    )
    parser.add_argument(
        "--created-by", default="user:agent-operator",
        help="Owning user principal recorded at agent registration.",
    )
    parser.add_argument(
        "--interval", type=float, default=2.0,
        help="Seconds between lifecycle cycles (default: 2.0).",
    )
    parser.add_argument(
        "--max-cycles", type=int, default=0,
        help="Stop after N cycles (0 = run forever).",
    )
    args = parser.parse_args(argv)

    agent = MarketplaceCoordinatorAgent(
        registry_url=args.registry_url,
        agent_id=args.agent_id,
        capability=args.capability,
        target_app_id=args.target_app,
        created_by=args.created_by,
    )
    if not agent.register():
        print("agent registration FAILED; exiting")
        return 1
    print("agent %s registered; entering work loop" % args.agent_id)

    cycles = 0
    try:
        while True:
            outcome = agent.single_cycle()
            print("cycle %d: %s" % (cycles + 1, outcome))
            cycles += 1
            if args.max_cycles and cycles >= args.max_cycles:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
