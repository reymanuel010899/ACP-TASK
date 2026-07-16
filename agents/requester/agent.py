"""AgentTrust demo Requester Agent (unit U5).

An independently-buildable A2A *client*. Given a capability id it:

1. searches a configurable registry (KTD5) for candidate providers,
2. picks one, negotiates a single-offer task (``task.request`` ->
   ``task.offer`` -> ``task.accept``, KTD6) over A2A ``message/send``,
   opting in to the trust layer via the ``A2A-Extensions`` header,
3. reads the trust metadata on the result and — crucially — treats the task
   as genuinely complete only when an **independent** verification says so
   (``evidence_status == "verified"``), never on the provider's own
   ``task_state`` alone (R4).

Hard constraint (R6): this package is written from the published spec and
schemas alone. It MUST NOT import from ``services``, ``registry``, or
``agents.provider`` — it talks to the registry and the provider only over
their HTTP contracts. A guard test enforces this.

The distinction the caller cares about (plan scenarios):

- ``verified``    — A2A COMPLETED *and* independently verified. The only
                    status that should be trusted as "done".
- ``rejected``    — the verifier rejected the evidence. NOT complete, and
                    distinct from an A2A-level ``failed``.
- ``unverified``  — completed at the A2A level but no independent
                    verification (verifier down, or provider without the
                    extension). Delivered, but unproven.
- ``provider_error`` — the provider returned a JSON-RPC error or an A2A
                    ``failed`` state. Distinct from ``rejected``.
- ``no_candidates`` — the registry returned nobody for the capability.
- ``registry_unreachable`` — the registry itself could not be reached.

Run: ``python -m agents.requester.agent --registry-url URL
[--capability terraform.generate] [--containers 2] [--load-balancer alb]
[--min-reputation 0.9]``
"""

import argparse
import json
import sys
import uuid

from typing import List, Optional
from urllib.parse import quote

import requests

from agents.requester.config import RequesterConfig

TRUST_EXTENSION_URI = "https://agenttrust.example/extensions/trust/v1"


class RequesterAgent(object):
    """Core requester logic; usable directly from tests (no CLI needed)."""

    def __init__(self, config):
        # type: (RequesterConfig) -> None
        self.config = config

    # -- discovery --------------------------------------------------------------

    def discover(self, capability=None, min_reputation=None):
        # type: (Optional[str], Optional[float]) -> List[dict]
        """Query the configured registry (KTD5). Raises on a dead registry."""
        capability = capability or self.config.capability
        if min_reputation is None:
            min_reputation = self.config.min_reputation
        params = {"capability": capability}
        if min_reputation is not None:
            params["min_reputation"] = min_reputation
        resp = requests.get(
            self.config.registry_url + "/search",
            params=params,
            timeout=self.config.http_timeout,
        )
        resp.raise_for_status()
        return resp.json().get("candidates", [])

    @staticmethod
    def select(candidates):
        # type: (List[dict]) -> Optional[dict]
        """Pick the best candidate: highest known verification rate, else first.

        A candidate with a proven rate is preferred over a neutral (null-rate)
        one; ties and all-neutral fields keep registry order (stable).
        """
        if not candidates:
            return None

        def rank(candidate):
            summary = candidate.get("reputation_summary") or {}
            rate = summary.get("verification_rate")
            # None (no history) sorts below any real rate.
            return rate if rate is not None else -1.0

        return max(candidates, key=rank)

    # -- A2A client -------------------------------------------------------------

    def _send(self, provider_url, payload):
        # type: (str, dict) -> dict
        """One A2A ``message/send`` JSON-RPC call, opting in to the trust layer.

        Returns the JSON-RPC envelope (with ``result`` or ``error``).
        """
        body = {
            "jsonrpc": "2.0",
            "id": "req-%s" % uuid.uuid4().hex,
            "method": "message/send",
            "params": {
                "message": {
                    "kind": "message",
                    "messageId": "msg-%s" % uuid.uuid4().hex,
                    "role": "user",
                    "parts": [{"kind": "data", "data": payload}],
                }
            },
        }
        resp = requests.post(
            provider_url,
            json=body,
            headers={"A2A-Extensions": TRUST_EXTENSION_URI},
            timeout=self.config.http_timeout,
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _data_part(message):
        # type: (dict) -> Optional[dict]
        for part in message.get("parts") or []:
            if isinstance(part, dict) and part.get("kind") == "data":
                return part.get("data")
        return None

    @staticmethod
    def _trust_metadata(message):
        # type: (dict) -> Optional[dict]
        metadata = message.get("metadata") or {}
        trust = metadata.get(TRUST_EXTENSION_URI)
        return trust if isinstance(trust, dict) else None

    # -- one full cycle ---------------------------------------------------------

    def run(self, capability=None, task_input=None, min_reputation=None):
        # type: (Optional[str], Optional[dict], Optional[float]) -> dict
        """Discover -> negotiate -> execute -> read verification. Never raises
        for an expected failure (no candidates, dead registry, provider error,
        rejected evidence): each maps to a distinct outcome status instead."""
        capability = capability or self.config.capability
        task_input = task_input if task_input is not None else self.config.task_input

        try:
            candidates = self.discover(capability, min_reputation)
        except requests.RequestException as exc:
            return _outcome(
                "registry_unreachable",
                capability=capability,
                reason="registry at %s could not be reached: %s"
                % (self.config.registry_url, exc),
            )

        provider = self.select(candidates)
        if provider is None:
            return _outcome(
                "no_candidates",
                capability=capability,
                reason="no provider in the registry offers capability %r%s"
                % (
                    capability,
                    " above the reputation threshold"
                    if (min_reputation or self.config.min_reputation)
                    else "",
                ),
            )

        principal_id = provider.get("principal_id")
        provider_url = (provider.get("agent_card") or {}).get("url")
        if not provider_url:
            return _outcome(
                "provider_error",
                capability=capability,
                provider_principal_id=principal_id,
                reason="chosen candidate has no agent_card.url to call",
            )

        # task.request -> task.offer
        try:
            offer_env = self._send(
                provider_url, {"type": "task.request", "input": task_input}
            )
        except requests.RequestException as exc:
            return _outcome(
                "provider_error",
                capability=capability,
                provider_principal_id=principal_id,
                reason="provider unreachable during task.request: %s" % exc,
            )
        if "error" in offer_env:
            return _outcome(
                "provider_error",
                capability=capability,
                provider_principal_id=principal_id,
                reason="provider refused task.request: %s"
                % offer_env["error"].get("message"),
            )
        offer = self._data_part(offer_env.get("result") or {}) or {}
        task_id = offer.get("task_id")
        if offer.get("type") != "task.offer" or not task_id:
            return _outcome(
                "provider_error",
                capability=capability,
                provider_principal_id=principal_id,
                reason="provider did not return a usable task.offer",
            )

        # task.accept -> task.result (single round, no counter-offer; KTD6)
        try:
            result_env = self._send(
                provider_url, {"type": "task.accept", "task_id": task_id}
            )
        except requests.RequestException as exc:
            return _outcome(
                "provider_error",
                capability=capability,
                provider_principal_id=principal_id,
                task_id=task_id,
                reason="provider unreachable during task.accept: %s" % exc,
            )
        if "error" in result_env:
            return _outcome(
                "provider_error",
                capability=capability,
                provider_principal_id=principal_id,
                task_id=task_id,
                reason="provider refused task.accept: %s"
                % result_env["error"].get("message"),
            )

        message = result_env.get("result") or {}
        result = self._data_part(message) or {}
        task_state = result.get("task_state")
        artifacts = result.get("artifacts") or {}
        trust = self._trust_metadata(message)

        return self._classify(
            capability=capability,
            principal_id=principal_id,
            task_id=task_id,
            task_state=task_state,
            artifacts=artifacts,
            trust=trust,
        )

    def _classify(
        self,
        capability,
        principal_id,
        task_id,
        task_state,
        artifacts,
        trust,
    ):
        # type: (str, str, str, Optional[str], dict, Optional[dict]) -> dict
        """Map A2A state + trust metadata onto a single outcome status.

        Independent verification is the gate for "done" (R4): a provider
        self-reporting ``completed`` is not enough — only the verifier's
        ``verified`` verdict earns the ``verified`` status.
        """
        evidence_status = trust.get("evidence_status") if trust else None
        verification_result = (
            trust.get("verification_result") if trust else None
        )

        # A2A-level failure is distinct from a trust-level rejection.
        if task_state and task_state != "completed":
            status = "provider_error"
        elif evidence_status == "verified":
            status = "verified"
        elif evidence_status == "rejected":
            # Delivered an artifact but independent verification rejected it:
            # NOT complete, and NOT the same as an A2A `failed`.
            status = "rejected"
        else:
            # completed at A2A level but pending / no extension: unproven.
            status = "unverified"

        return _outcome(
            status,
            capability=capability,
            provider_principal_id=principal_id,
            task_id=task_id,
            task_state=task_state,
            evidence_status=evidence_status,
            artifacts=artifacts,
            verification_result=verification_result,
            reason=_REASONS[status],
        )


_REASONS = {
    "verified": "task completed and independently verified",
    "rejected": "artifact delivered but independent verification rejected it",
    "unverified": "task completed but not independently verified "
    "(verifier unreachable or provider without the trust extension)",
    "provider_error": "provider failed the task at the A2A level",
}


def _outcome(status, **fields):
    # type: (str, object) -> dict
    outcome = {
        "status": status,
        "verified": status == "verified",
        "capability": fields.get("capability"),
        "provider_principal_id": fields.get("provider_principal_id"),
        "task_id": fields.get("task_id"),
        "task_state": fields.get("task_state"),
        "evidence_status": fields.get("evidence_status"),
        "artifacts": fields.get("artifacts") or {},
        "verification_result": fields.get("verification_result"),
        "reason": fields.get("reason", ""),
    }
    return outcome


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None):
    # type: (Optional[List[str]]) -> int
    parser = argparse.ArgumentParser(
        description="AgentTrust demo Requester Agent"
    )
    parser.add_argument(
        "--registry-url",
        required=True,
        help="Base URL of a registry speaking the U4 API contract (KTD5).",
    )
    parser.add_argument("--capability", default=None)
    parser.add_argument(
        "--containers",
        type=int,
        default=None,
        help="Number of containers for the demo Terraform task.",
    )
    parser.add_argument("--load-balancer", default=None)
    parser.add_argument(
        "--min-reputation",
        type=float,
        default=None,
        help="Only consider providers whose verification_rate is >= this.",
    )
    args = parser.parse_args(argv)

    task_input = None
    if args.containers is not None or args.load_balancer is not None:
        task_input = dict(RequesterConfig(args.registry_url).task_input)
        if args.containers is not None:
            task_input["containers"] = args.containers
        if args.load_balancer is not None:
            task_input["load_balancer"] = args.load_balancer

    config = RequesterConfig(
        registry_url=args.registry_url,
        capability=args.capability or "terraform.generate",
        task_input=task_input,
        min_reputation=args.min_reputation,
    )
    outcome = RequesterAgent(config).run()
    json.dump(outcome, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    # Exit non-zero unless the task was genuinely, independently verified.
    return 0 if outcome["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
