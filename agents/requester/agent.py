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

    def _send(self, provider_url, payload, token=None):
        # type: (str, dict, Optional[str]) -> dict
        """One A2A ``message/send`` JSON-RPC call, opting in to the trust layer.

        When ``token`` is set it is presented as ``Authorization: Bearer`` for
        providers that require auth (RFC-0002 §7.2). Returns the JSON-RPC
        envelope (with ``result`` or ``error``).
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
        headers = {"A2A-Extensions": TRUST_EXTENSION_URI}
        if token is not None:
            headers["Authorization"] = "Bearer %s" % token
        resp = requests.post(
            provider_url,
            json=body,
            headers=headers,
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
        price_paid=None,
        currency=None,
        offers_considered=0,
    ):
        # type: (str, str, str, Optional[str], dict, Optional[dict], Optional[float], Optional[str], int) -> dict
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
            price_paid=price_paid,
            currency=currency,
            offers_considered=offers_considered,
            reason=_REASONS[status],
        )

    # -- competitive negotiation (U4) -------------------------------------------

    def run_competitive(self, capability=None, task_input=None, min_reputation=None):
        # type: (Optional[str], Optional[dict], Optional[float]) -> dict
        """Discover many providers, collect offers, run one counter round, and
        pick the fair-price winner that clears the trust gate (R1/R3/R4).

        Reputation-per-capability is a hard eligibility floor (applied at
        discovery); among the eligible, price competes, with verified-portfolio
        assurance deciding ties in favor of proven providers over unproven ones
        (KTD-N3). Never raises for an expected failure — each maps to a status.
        """
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
        if not candidates:
            return _outcome(
                "no_candidates",
                capability=capability,
                reason="no provider clears the reputation floor for %r"
                % capability,
            )

        # Fan out to the top-N candidates by known reputation (KTD-N4).
        # None (no history) sorts below any real rate.
        candidates = sorted(
            candidates,
            key=lambda c: _rate_of(c) if _rate_of(c) is not None else -1.0,
            reverse=True,
        )[: self.config.fan_out]

        offers = []  # each: dict(meta + offer + price + proven)
        for index, candidate in enumerate(candidates):
            meta = self._candidate_meta(candidate, index)
            if not meta["provider_url"]:
                continue
            # Not eligible: this provider requires auth and we hold no token
            # for it (R3). Skip it — never fail the whole request.
            if meta["requires_auth"] and not meta["token"]:
                continue
            offer = self._request_offer(
                meta["provider_url"], task_input, meta["token"]
            )
            if offer is None:
                continue  # unreachable / refused / 401 -> drop this candidate
            meta["offer"] = offer
            meta["price"] = offer.get("price")
            meta["task_id"] = offer.get("task_id")
            meta["proven"] = self._is_proven(meta, capability)
            offers.append(meta)

        offers = [o for o in offers if isinstance(o.get("price"), (int, float))]
        if not offers:
            return _outcome(
                "no_candidates",
                capability=capability,
                reason="no candidate returned a usable priced offer",
            )

        # One counter round to the cheapest `top_counter` offers (KTD-N4).
        for meta in sorted(offers, key=lambda o: o["price"])[
            : self.config.top_counter
        ]:
            proposed = round(meta["price"] * self.config.counter_fraction, 4)
            updated = self._counter(
                meta["provider_url"], meta["task_id"], proposed, meta["token"]
            )
            if updated is not None and isinstance(
                updated.get("price"), (int, float)
            ):
                meta["price"] = updated["price"]  # accept-or-hold outcome

        winner = self._select_winner(offers)

        # Close with the winner and read the trust gate. Guard the accept the
        # same way as request/counter: a winner that dies in the gap between
        # the counter round and the accept must map to provider_error, not
        # raise out of this method (its docstring promises it never does).
        try:
            result_env = self._send(
                winner["provider_url"],
                {"type": "task.accept", "task_id": winner["task_id"]},
                token=winner["token"],
            )
        except requests.RequestException as exc:
            return _outcome(
                "provider_error",
                capability=capability,
                provider_principal_id=winner["principal_id"],
                task_id=winner["task_id"],
                offers_considered=len(offers),
                reason="winner unreachable during task.accept: %s" % exc,
            )
        if "error" in result_env:
            return _outcome(
                "provider_error",
                capability=capability,
                provider_principal_id=winner["principal_id"],
                task_id=winner["task_id"],
                offers_considered=len(offers),
                reason="winner refused task.accept: %s"
                % result_env["error"].get("message"),
            )
        message = result_env.get("result") or {}
        result = self._data_part(message) or {}
        trust = self._trust_metadata(message)
        return self._classify(
            capability=capability,
            principal_id=winner["principal_id"],
            task_id=winner["task_id"],
            task_state=result.get("task_state"),
            artifacts=result.get("artifacts") or {},
            trust=trust,
            price_paid=winner["price"],
            currency=(winner.get("offer") or {}).get("currency"),
            offers_considered=len(offers),
        )

    def _candidate_meta(self, candidate, index):
        # type: (dict, int) -> dict
        card = candidate.get("agent_card") or {}
        principal_id = candidate.get("principal_id")
        return {
            "principal_id": principal_id,
            "provider_url": card.get("url"),
            "verification_rate": _rate_of(candidate),
            "requires_auth": _card_requires_auth(card),
            "token": self.config.provider_tokens.get(principal_id),
            "index": index,
        }

    def _is_proven(self, meta, capability):
        # type: (dict, str) -> bool
        """Proven = has a per-capability reputation rate (registry-attested),
        or verified portfolio work checked against the requester's OWN trusted
        verifier. Judged only from verified facts (R4).

        The portfolio is deliberately NOT fetched from a candidate-declared
        URL: an attacker controls that field and could return fake 'verified'
        entries to jump the trust gate. With no trusted verifier configured, an
        unproven candidate stays unproven.
        """
        if meta.get("verification_rate") is not None:
            return True
        if not self.config.require_portfolio_for_unproven:
            return True
        if not self.config.verification_url:
            return False
        portfolio = self._fetch_portfolio(
            self.config.verification_url, meta.get("principal_id"), capability
        )
        return len(portfolio) > 0

    def _fetch_portfolio(self, verification_url, principal_id, capability):
        # type: (Optional[str], Optional[str], str) -> List[dict]
        """Best-effort verified-work lookup; any failure means 'no portfolio'."""
        if not verification_url or not principal_id:
            return []
        try:
            resp = requests.get(
                verification_url.rstrip("/")
                + "/portfolio/"
                + quote(principal_id, safe=""),
                params={"capability_id": capability},
                timeout=self.config.http_timeout,
            )
            resp.raise_for_status()
            entries = resp.json().get("portfolio", [])
        except (requests.RequestException, ValueError):
            return []
        return entries if isinstance(entries, list) else []

    def _request_offer(self, provider_url, task_input, token=None):
        # type: (str, dict, Optional[str]) -> Optional[dict]
        try:
            env = self._send(
                provider_url,
                {"type": "task.request", "input": task_input},
                token=token,
            )
        except requests.RequestException:
            return None
        if "error" in env:
            return None
        offer = self._data_part(env.get("result") or {}) or {}
        if offer.get("type") != "task.offer" or not offer.get("task_id"):
            return None
        return offer

    def _counter(self, provider_url, task_id, proposed_price, token=None):
        # type: (str, str, float, Optional[str]) -> Optional[dict]
        try:
            env = self._send(
                provider_url,
                {
                    "type": "task.counter",
                    "task_id": task_id,
                    "proposed_price": proposed_price,
                },
                token=token,
            )
        except requests.RequestException:
            return None
        if "error" in env:
            return None
        return self._data_part(env.get("result") or {})

    @staticmethod
    def _select_winner(offers):
        # type: (List[dict]) -> dict
        """Cheapest offer wins; proven providers are preferred over unproven,
        then higher reputation, then discovery order (KTD-N3)."""
        proven = [o for o in offers if o.get("proven")]
        pool = proven if proven else offers

        def key(o):
            rate = o.get("verification_rate")
            return (
                o["price"],
                -(rate if rate is not None else -1.0),
                o["index"],
            )

        return min(pool, key=key)


def _rate_of(candidate):
    # type: (dict) -> Optional[float]
    summary = candidate.get("reputation_summary") or {}
    return summary.get("verification_rate")


def _card_requires_auth(agent_card):
    # type: (dict) -> bool
    """True if the provider's Agent Card declares an auth requirement (A2A
    ``security``), meaning a caller must present a credential (RFC-0002 §7)."""
    security = agent_card.get("security")
    return isinstance(security, list) and len(security) > 0


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
        "price_paid": fields.get("price_paid"),
        "currency": fields.get("currency"),
        "offers_considered": fields.get("offers_considered", 0),
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
    parser.add_argument(
        "--fan-out",
        type=int,
        default=None,
        help="How many candidates to request competing offers from.",
    )
    parser.add_argument(
        "--top-counter",
        type=int,
        default=None,
        help="How many of the cheapest offers to send a counter-offer to.",
    )
    parser.add_argument(
        "--single-offer",
        action="store_true",
        help="Use the legacy single-offer path instead of competitive "
        "negotiation (graceful-degradation / compatibility).",
    )
    parser.add_argument(
        "--verification-url",
        default=None,
        help="A TRUSTED verification service to check candidate portfolios "
        "against. Portfolio assurance is ignored unless this is set.",
    )
    parser.add_argument(
        "--provider-token",
        action="append",
        default=None,
        dest="provider_tokens",
        metavar="PRINCIPAL_ID=TOKEN",
        help="Bearer token to present to a provider that requires auth "
        "(repeatable).",
    )
    args = parser.parse_args(argv)

    provider_tokens = {}
    for entry in args.provider_tokens or []:
        principal, _, token = entry.partition("=")
        if principal and token:
            provider_tokens[principal] = token

    task_input = None
    if args.containers is not None or args.load_balancer is not None:
        task_input = dict(RequesterConfig(args.registry_url).task_input)
        if args.containers is not None:
            task_input["containers"] = args.containers
        if args.load_balancer is not None:
            task_input["load_balancer"] = args.load_balancer

    kwargs = {}
    if args.fan_out is not None:
        kwargs["fan_out"] = args.fan_out
    if args.top_counter is not None:
        kwargs["top_counter"] = args.top_counter
    config = RequesterConfig(
        registry_url=args.registry_url,
        capability=args.capability or "terraform.generate",
        task_input=task_input,
        min_reputation=args.min_reputation,
        verification_url=args.verification_url,
        provider_tokens=provider_tokens,
        **kwargs
    )
    agent = RequesterAgent(config)
    outcome = agent.run() if args.single_offer else agent.run_competitive()
    json.dump(outcome, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    # Exit non-zero unless the task was genuinely, independently verified.
    return 0 if outcome["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
