"""Orchestrator tool set over the existing ecosystem rails (unit U22).

:class:`OrchestratorTools` is the bounded set of actions the orchestrator
brain (U21) may take. Each tool wraps an EXISTING ``libs/`` rail — nothing
here talks to a service directly:

* ``discover_candidates``        -> ``libs.federation_client`` (app
  discovery) UNION ``libs.agent_marketplace_client`` (agent search),
  normalized to ``[{id, kind, reputation, price?, speed?}]``.
* ``rank_candidates``            -> pure ordering: reputation first
  (``verification_rate`` desc, then ``tasks_verified`` desc — the fields
  the Registry/marketplace rails actually expose, RFC-0001), then price
  asc, then speed asc as documented tie-breakers.
* ``request_terms``              -> ``libs.agent_coordination`` /
  ``libs.p2p_client``. The apps expose NO dedicated "quote" endpoint, so
  terms are derived from the work-discovery/bid flow the rails support
  (RFC-0003/U10): ``list.work_opportunities`` for what work exists, and
  the ``proposed_terms`` carried on a task's bids (``get.task_status``)
  for the actual terms/cost candidates offered.
* ``request_credential_access``  -> GATED through the U23
  :class:`~agents.orchestrator.approval.ApprovalGate` FIRST; only an
  approved decision ever reaches ``libs.vault_client``. Denials come back
  as data (``{"granted": False, ...}``), never as exceptions, so the
  agent loop keeps running.
* ``report_to_user``             -> injectable reporter hook (defaults to
  ``print``) so the loop can surface progress.

Session handling mirrors the optional-session pattern of the client
libraries themselves (``VaultClient``, ``P2PClient``, ``AgentCoordinator``,
``FederationClient``): pass a :class:`libs.session.SessionContext` and
every P2P/vault call is signed; pass ``None`` and the calls go unsigned,
byte-for-byte like the pre-signing clients.

:func:`build_beta_tools` exposes the SAME instance methods to the Anthropic
Tool Runner as thin ``@beta_tool`` wrappers (schemas generated from the
signatures/docstrings), so ``ClaudeBrain``'s tool loop and direct callers
(``RuleBrain``, tests) share ONE implementation.
"""

import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

import requests
import jsonschema
from anthropic import beta_tool

from libs.agent_coordination import AgentCoordinationError
from libs.federation_client import FederationClient, FederationError
from libs.p2p_client import P2PError

logger = logging.getLogger(__name__)

DEFAULT_PRINCIPAL_ID = "agent:orchestrator"
DEFAULT_TIMEOUT = 5.0

#: Sort keys treat "no reputation history" as neutral (RFC-0001: null,
#: never 0.0) — neutral candidates rank BELOW any candidate with a rate.
_NEUTRAL_RATE = -1.0

#: Shared, courteous explanation for a candidate whose ``kind`` is
#: "agent": the current coordination rails (``AgentCoordinator``/P2P) only
#: execute work inside registered apps, never other agent principals —
#: reused by both the deterministic path (``agents.orchestrator.agent``)
#: and ``request_terms`` below so an agent-kind candidate never surfaces a
#: raw ``AgentCoordinationError``/``P2PError`` (R4, KTD3).
AGENT_CANDIDATE_OUTCOME = (
    "el mejor candidato es un agente; los rieles actuales solo ejecutan "
    "trabajo dentro de apps"
)


def _parse_finite_cost(cost):
    # type: (str) -> Optional[Decimal]
    """Parse a model-supplied cost string into a finite ``Decimal``.

    Returns ``None`` for anything that doesn't parse to a finite value
    -- including "NaN"/"Infinity", which construct successfully but
    then raise ``decimal.InvalidOperation`` on the very next comparison
    (the R6 auto-approve-floor ``max()`` both beta-tool wrappers apply,
    and ``ApprovalGate.require``'s own threshold comparisons) if not
    caught here first.
    """
    try:
        cost_decimal = Decimal(cost)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not cost_decimal.is_finite():
        return None
    return cost_decimal


def submit_work_bid(coordinator, candidate, opportunities, agent_principal_id):
    # type: (Any, dict, List[dict], str) -> dict
    """Shared bid-submission core (U5, KTD6): the ONE implementation that
    actually submits a signed work bid, called from BOTH driving paths --
    :meth:`OrchestratorTools.execute_work` (self-gated, tool-runner path)
    and :meth:`agents.orchestrator.agent.OrchestratorAgent._execute`
    (deterministic path, already gated by ``_handle_stepwise`` before it
    runs) -- so the two never maintain independently hand-synced copies.

    Given an already-discovered ``candidate`` (``{"id", "kind", ...}``)
    and its already-discovered open ``opportunities``, this bids on the
    first opportunity over the signed coordinator rail. Anything
    non-biddable (no coordinator, an agent-kind candidate, no open work)
    completes with an explanatory ``outcome`` instead of an invented
    endpoint; a rail failure while bidding (a stale opportunity claimed
    by another bidder between discovery and bid, transport/auth
    failure) comes back as ``{"executed": False, "reason": ...}`` rather
    than raising into either caller's loop.
    """
    if coordinator is None:
        return {
            "executed": False,
            "outcome": "no coordinator rail configured; nothing was "
            "executed",
        }
    if candidate.get("kind") == "agent":
        return {
            "executed": False,
            "outcome": AGENT_CANDIDATE_OUTCOME,
        }
    if not opportunities:
        return {
            "executed": False,
            "outcome": "no hay trabajo abierto en %s por ahora"
            % candidate.get("id"),
        }
    opportunity = opportunities[0]
    try:
        bid = coordinator.submit_bid(
            candidate["id"],
            opportunity["id"],
            "handled by %s on behalf of the user" % agent_principal_id,
        )
    except (AgentCoordinationError, P2PError) as exc:
        logger.warning(
            "bid submission failed for %s/%s", candidate.get("id"),
            opportunity.get("id"), exc_info=True,
        )
        return {"executed": False, "reason": str(exc)}
    return {
        "executed": True,
        "action": "bid_submitted",
        "task_id": opportunity["id"],
        "bid": bid,
        "outcome": "se envió una oferta por la tarea %s"
        % opportunity["id"],
    }


class OutcomeTracker(object):
    """Per-request outcome tracker for the tool-runner path (U6, KTD2/KTD7).

    A resettable attribute living on the shared :class:`OrchestratorTools`
    instance (``tools._outcome``) -- reset immediately before each
    ``run_tool_loop`` call in
    :meth:`agents.orchestrator.agent.OrchestratorAgent._handle_with_tool_runner`,
    **never** rebuilt into the cached ``@beta_tool`` closures themselves
    (the U21-U26 simplification pass, commit ``46ce3b7``, keeps those
    closures cached and request-independent). ``execute_work`` and
    ``request_credential_access`` read/update this SAME object at CALL
    time -- an attribute lookup on ``self`` -- so:

    * ``running_cost`` accumulates every APPROVED call's cost across one
      loop, and both gated tools check the running total (not just their
      own call's cost) against ``policy.hard_ceiling`` before authorizing
      the next call, so several individually-small approvals cannot
      aggregate past the ceiling within one loop (R12/KTD7).
    * what actually happened is recorded so ``Result.status`` can be
      derived honestly after the loop ends, per KTD2's explicit
      precedence: ``done`` (execute_work ever reported real execution,
      never un-set once true) > ``declined`` (a gate denial recorded,
      nothing executed) > ``no_candidate`` (discovery came back empty,
      nothing executed or denied) > ``failed`` (nothing terminal
      recorded, e.g. ``max_iterations`` exhausted).
    """

    def __init__(self):
        # type: () -> None
        self.executed = False
        self.executed_outcome = None  # type: Optional[str]
        self.executed_app_id = None  # type: Optional[str]
        self.declined = False
        self.declined_reason = None  # type: Optional[str]
        self.no_candidate = False
        self.running_cost = Decimal("0")

    def record_executed(self, outcome, app_id=None):
        # type: (Optional[str], Optional[str]) -> None
        """Real work committed -- KTD2: nothing later un-executes this,
        so once set it stays set for the rest of the loop."""
        self.executed = True
        self.executed_outcome = outcome
        self.executed_app_id = app_id

    def record_declined(self, reason):
        # type: (Optional[str]) -> None
        self.declined = True
        self.declined_reason = reason

    def record_no_candidate(self):
        # type: () -> None
        self.no_candidate = True

    def status(self):
        # type: () -> str
        """KTD2's explicit precedence: done > declined > no_candidate >
        failed."""
        if self.executed:
            return "done"
        if self.declined:
            return "declined"
        if self.no_candidate:
            return "no_candidate"
        return "failed"


# -- P2P provider rail (registry /search + direct A2A negotiation) ----------
#
# Providers (SDK agents, connected agents) are not federation apps: they
# publish an agent card to the Registry and speak the negotiation vocabulary
# (task.request -> task.offer -> task.accept -> task.result) directly at their
# card url. These helpers let the orchestrator engage that rail with ONE
# implementation shared by the stepwise and tool-runner paths.


def _a2a_send(url, payload, timeout):
    # type: (str, dict, float) -> dict
    """One A2A ``message/send`` call; returns the inner data part."""
    body = {
        "jsonrpc": "2.0",
        "id": "req-%s" % uuid.uuid4().hex,
        "method": "message/send",
        "params": {"message": {
            "kind": "message",
            "messageId": "msg-%s" % uuid.uuid4().hex,
            "role": "user",
            "parts": [{"kind": "data", "data": payload}],
        }},
    }
    resp = requests.post(url, json=body, timeout=timeout)
    resp.raise_for_status()
    envelope = resp.json()
    if "error" in envelope:
        raise P2PError("provider error: %s" % envelope["error"].get("message"))
    for part in (envelope.get("result") or {}).get("parts") or []:
        if isinstance(part, dict) and part.get("kind") == "data":
            return part.get("data") or {}
    return {}


def registry_provider_candidates(registry_url, capability, timeout):
    # type: (str, str, float) -> List[dict]
    """P2P providers offering ``capability``, straight from the Registry's
    /search — normalized to the candidate shape, with the card url attached
    so terms/execution can engage the provider directly."""
    try:
        resp = requests.get(
            "%s/search" % registry_url,
            params={"capability": capability},
            timeout=timeout,
        )
        resp.raise_for_status()
        raw = resp.json().get("candidates", [])
    except (requests.RequestException, ValueError):
        logger.warning(
            "registry provider search unavailable for %r (skipped)",
            capability, exc_info=True,
        )
        return []
    candidates = []  # type: List[dict]
    for entry in raw:
        card = entry.get("agent_card") or {}
        principal_id = entry.get("principal_id")
        if not principal_id or not card.get("url"):
            continue
        summary = entry.get("reputation_summary") or {}
        skill = next(
            (
                item
                for item in card.get("skills") or []
                if isinstance(item, dict) and item.get("id") == capability
            ),
            {},
        )
        candidates.append({
            "id": principal_id,
            "kind": "provider",
            "reputation": {
                "verification_rate": summary.get("verification_rate"),
                "tasks_verified": summary.get("tasks_verified") or 0,
            },
            "card_url": card["url"],
            "name": card.get("name") or principal_id,
            "input_schema": skill.get("inputSchema"),
        })
    return candidates


def provider_request_offer(card_url, capability, task_input, timeout):
    # type: (str, str, dict, float) -> dict
    """task.request -> the provider's task.offer (price, task_id)."""
    return _a2a_send(
        card_url,
        {
            "type": "task.request",
            "capability_id": capability,
            "input": task_input or {},
        },
        timeout,
    )


def validate_provider_input(candidate, capability, task_input):
    # type: (dict, str, dict) -> None
    """Validate inputs against the exact discovered capability schema."""
    schema = candidate.get("input_schema")
    if not isinstance(schema, dict):
        raise ValueError(
            "provider %s does not publish a required input schema for %s"
            % (candidate.get("id"), capability)
        )
    try:
        jsonschema.Draft7Validator(schema).validate(task_input or {})
    except jsonschema.ValidationError as exc:
        path = ".".join(str(item) for item in exc.absolute_path)
        raise ValueError(
            "invalid %s input at %s: %s"
            % (capability, path or exc.validator or "input", exc.message)
        )


def provider_accept(card_url, task_id, timeout, action_broker=None):
    # type: (str, str, float) -> dict
    """task.accept -> the provider's task.result (output + evidence)."""
    result = _a2a_send(
        card_url, {"type": "task.accept", "task_id": task_id}, timeout
    )
    request = result.pop("broker_request", None)
    if request is None:
        return result
    if action_broker is None:
        raise P2PError("provider requested an unavailable broker operation")
    if not isinstance(request, dict):
        raise P2PError("provider returned an invalid broker operation")
    lease = request.get("lease")
    binding = request.get("binding")
    payload = request.get("payload")
    if (
        not isinstance(lease, str)
        or not lease
        or not isinstance(binding, dict)
        or not isinstance(payload, dict)
    ):
        raise P2PError("provider returned an invalid broker operation")
    status, response = action_broker.execute(lease, binding, payload)
    if status not in (200, 202):
        raise P2PError("broker refused the provider operation")
    result["broker_result"] = response
    if status == 202:
        result["broker_status"] = response.get(
            "status", "execution_unknown"
        )
    return result


def plan_subtasks(subtasks, max_subtasks=5):
    """Validate and normalize a small ordered dependency plan."""
    if (
        not isinstance(subtasks, list)
        or not subtasks
        or len(subtasks) > int(max_subtasks)
    ):
        return {
            "status": "invalid",
            "message": "subtasks must contain between 1 and %d steps"
            % int(max_subtasks),
        }

    normalized = []
    prior_ids = set()
    for index, raw in enumerate(subtasks):
        if not isinstance(raw, dict):
            return {"status": "invalid", "message": "each subtask must be an object"}
        step_id = raw.get("id") or "step-%d" % (index + 1)
        capability = raw.get("capability")
        dependencies = raw.get("depends_on", [])
        task_input = raw.get("input", {})
        if not isinstance(step_id, str) or not step_id or step_id in prior_ids:
            return {"status": "invalid", "message": "subtask ids must be unique"}
        if not isinstance(capability, str) or not capability:
            return {"status": "invalid", "message": "capability is required"}
        if not isinstance(task_input, dict):
            return {"status": "invalid", "message": "subtask input must be an object"}
        if (
            not isinstance(dependencies, list)
            or any(
                not isinstance(value, str) or value not in prior_ids
                for value in dependencies
            )
        ):
            return {
                "status": "invalid",
                "message": "dependencies must reference earlier subtasks",
            }
        normalized.append(
            {
                "id": step_id,
                "capability": capability,
                "input": json.loads(json.dumps(task_input)),
                "depends_on": list(dict.fromkeys(dependencies)),
            }
        )
        prior_ids.add(step_id)
    return {"status": "ready", "subtasks": normalized}


class ChainReferenceError(ValueError):
    """A chained input refers to an unavailable prior output."""


def _chain_reference(path, completed):
    pieces = path.split(".")
    if (
        len(pieces) < 3
        or pieces[0] not in completed
        or pieces[1] not in ("output", "receipt")
    ):
        raise ChainReferenceError("unknown chain reference")
    value = completed[pieces[0]].get(pieces[1])
    for piece in pieces[2:]:
        if not isinstance(value, dict) or piece not in value:
            raise ChainReferenceError("unknown chain reference")
        value = value[piece]
    return value


def _resolve_chain_input(value, completed):
    if isinstance(value, dict):
        if set(value) == {"$ref"} and isinstance(value["$ref"], str):
            return _chain_reference(value["$ref"], completed)
        return {
            key: _resolve_chain_input(item, completed)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_resolve_chain_input(item, completed) for item in value]
    return value


class ChainExecutor(object):
    """Execute a bounded chain while retaining successful external receipts."""

    def __init__(self):
        self._lock = threading.RLock()
        self._chains = {}

    def execute(self, chain_id, subtasks, executor):
        planned = plan_subtasks(subtasks)
        if planned["status"] != "ready":
            return planned
        if not isinstance(chain_id, str) or not chain_id:
            return {"status": "invalid", "message": "chain_id is required"}
        fingerprint = json.dumps(
            planned["subtasks"], sort_keys=True, separators=(",", ":")
        )
        with self._lock:
            chain = self._chains.get(chain_id)
            if chain is None:
                chain = {"fingerprint": fingerprint, "completed": {}}
                self._chains[chain_id] = chain
            elif chain["fingerprint"] != fingerprint:
                return {
                    "status": "invalid",
                    "message": "an existing chain cannot change its plan",
                }

            completed = chain["completed"]
            for original in planned["subtasks"]:
                step_id = original["id"]
                if step_id in completed:
                    continue
                if any(dep not in completed for dep in original["depends_on"]):
                    return self._partial(chain, step_id)
                try:
                    task_input = _resolve_chain_input(
                        original["input"], completed
                    )
                except ChainReferenceError:
                    return self._partial(
                        chain, step_id, "A prior output reference is unavailable."
                    )
                step = dict(original)
                step["input"] = task_input
                try:
                    result = executor(step)
                except Exception:
                    return self._partial(
                        chain, step_id, "The subtask could not be completed."
                    )
                if (
                    not isinstance(result, dict)
                    or result.get("success") is False
                    or result.get("status") in ("failed", "error")
                ):
                    return self._partial(
                        chain, step_id, "The subtask reported a failure."
                    )
                completed[step_id] = {
                    "output": result.get("output", {}),
                    "receipt": result.get(
                        "receipt", {"status": "completed"}
                    ),
                }
            return self._result(chain, "complete")

    @staticmethod
    def _result(chain, status, failed_step=None, message=None):
        completed = list(chain["completed"])
        result = {
            "status": status,
            "completed": completed,
            "outputs": {
                key: value["output"]
                for key, value in chain["completed"].items()
            },
            "receipts": {
                key: value["receipt"]
                for key, value in chain["completed"].items()
            },
        }
        if failed_step is not None:
            result.update(
                {
                    "failed_step": failed_step,
                    "message": message,
                    "compensation": (
                        "No automatic rollback was attempted. Completed "
                        "external effects and their receipts were preserved."
                    ),
                }
            )
        return result

    def _partial(self, chain, failed_step, message=None):
        return self._result(
            chain,
            "partial_failure",
            failed_step=failed_step,
            message=message or "A dependency was not completed.",
        )


class OrchestratorTools(object):
    """The orchestrator's bounded action set over the existing rails.

    Rails may be wired by URL (``registry_url``, ``agent_marketplace_url``,
    ``vault_url`` — real clients are built lazily from them) or by
    injecting ready-made client instances (preferred in tests). An injected
    client always wins over its URL. Any rail left unconfigured simply
    contributes nothing (discovery) or fails closed (vault).

    ``gate`` is the U23 :class:`~agents.orchestrator.approval.ApprovalGate`;
    without one, ``request_credential_access`` fails closed. ``session`` is
    an optional :class:`libs.session.SessionContext` passed straight down
    to the client libraries (their own optional-session pattern).
    """

    def __init__(
        self,
        registry_url=None,
        agent_marketplace_url=None,
        vault_url=None,
        gate=None,
        agent_principal_id=DEFAULT_PRINCIPAL_ID,
        session=None,
        federation_client=None,
        marketplace_client=None,
        coordinator=None,
        vault_client=None,
        action_broker=None,
        reporter=None,
        timeout=DEFAULT_TIMEOUT,
    ):
        # type: (...) -> None
        self._chain_executor = ChainExecutor()
        self.action_broker = action_broker
        self.gate = gate
        self.agent_principal_id = agent_principal_id
        self.session = session
        self.reporter = reporter if reporter is not None else print
        #: P2P provider rail (the protocol itself): providers register their
        #: card in the Registry and are discovered via GET /search, then
        #: engaged DIRECTLY at their card url (task.request -> offer ->
        #: accept). Kept as plain URL + timeout — no extra client object.
        self.registry_url = registry_url.rstrip("/") if registry_url else None
        self.p2p_timeout = timeout
        #: Per-request outcome tracker (U6, KTD2/KTD7) -- ``None`` until
        #: ``OrchestratorAgent._handle_with_tool_runner`` resets it to a
        #: fresh :class:`OutcomeTracker` immediately before each
        #: ``run_tool_loop`` call. Direct/RuleBrain callers never set it,
        #: so ``execute_work``/``request_credential_access`` fall back to
        #: their pre-U6, single-call gating behavior (no cumulative sum).
        # Thread-local because the HTTP concierge serves concurrent requests
        # through one shared OrchestratorTools instance. A process-global
        # tracker lets one user's execution/decline/cost leak into another
        # user's result while their LLM loops overlap.
        self._outcome_context = threading.local()
        self._outcome = None

        self.federation = federation_client
        if self.federation is None and registry_url:
            self.federation = FederationClient(
                registry_url, timeout=timeout, session=session
            )

        self.marketplace = marketplace_client
        if self.marketplace is None and agent_marketplace_url:
            from libs.agent_marketplace_client import AgentMarketplaceClient

            self.marketplace = AgentMarketplaceClient(
                agent_marketplace_url, timeout=timeout, session=session
            )

        self.coordinator = coordinator
        if self.coordinator is None and registry_url:
            from libs.agent_coordination import AgentCoordinator

            self.coordinator = AgentCoordinator(
                registry_url, agent_principal_id,
                timeout=timeout, session=session,
            )

        self.vault = vault_client
        if self.vault is None and vault_url:
            from libs.vault_client import VaultClient

            self.vault = VaultClient(
                vault_url, timeout=timeout, session=session
            )

    @property
    def _outcome(self):
        # type: () -> Optional[OutcomeTracker]
        return getattr(self._outcome_context, "value", None)

    @_outcome.setter
    def _outcome(self, value):
        # type: (Optional[OutcomeTracker]) -> None
        self._outcome_context.value = value

    # -- discovery ---------------------------------------------------------

    def discover_candidates(self, capability):
        # type: (str) -> List[dict]
        """Union of federation app discovery and agent-marketplace search.

        Returns a normalized candidate list ``[{id, kind, reputation}]``
        where ``kind`` is ``"app"`` or ``"agent"`` and ``reputation`` is
        ``{"verification_rate": float|None, "tasks_verified": int}`` for
        agents (the fields the rails expose, RFC-0001) or ``None`` for
        apps (apps carry no reputation record). An unknown capability is
        an EMPTY list, never an error (the Registry answers ``[]``); an
        unreachable rail contributes nothing rather than aborting
        discovery on the other rail.
        """
        # The rails are independent services taking the same input; query
        # them concurrently so one slow rail's latency (up to its timeout)
        # doesn't stack on top of the others'.
        sources = []
        if self.federation is not None:
            sources.append(lambda: self._federation_candidates(capability))
        if self.marketplace is not None:
            sources.append(lambda: self._marketplace_candidates(capability))
        if self.registry_url:
            # The protocol's own rail: P2P providers registered in the
            # Registry (SDK/connected agents) — not hardcoded anywhere.
            sources.append(lambda: registry_provider_candidates(
                self.registry_url, capability, self.p2p_timeout
            ))
        if not sources:
            return []
        if len(sources) == 1:
            return sources[0]()
        with ThreadPoolExecutor(max_workers=len(sources)) as executor:
            futures = [executor.submit(source) for source in sources]
            candidates = []  # type: List[dict]
            for future in futures:
                candidates.extend(future.result())
            return candidates

    def _federation_candidates(self, capability):
        # type: (str) -> List[dict]
        try:
            apps = self.federation.discover_apps(capability=capability)
        except FederationError:
            logger.warning(
                "federation discovery unavailable for %r (skipped)",
                capability, exc_info=True,
            )
            apps = []
        return [
            {"id": app["app_id"], "kind": "app", "reputation": None}
            for app in apps
            if app.get("app_id")
        ]

    def _marketplace_candidates(self, capability):
        # type: (str) -> List[dict]
        try:
            agents = self.marketplace.search_agents(capability)
        except Exception:
            logger.warning(
                "agent-marketplace search unavailable for %r (skipped)",
                capability, exc_info=True,
            )
            agents = []
        candidates = []  # type: List[dict]
        for agent in agents:
            principal_id = agent.get("principal_id")
            if not principal_id:
                continue
            reputation = agent.get("reputation") or {}
            candidates.append({
                "id": principal_id,
                "kind": "agent",
                "reputation": {
                    "verification_rate": reputation.get(
                        "verification_rate"
                    ),
                    "tasks_verified": reputation.get(
                        "tasks_verified"
                    ) or 0,
                },
            })
        return candidates

    def _find_provider(self, candidate_id, capability, kind=None):
        # type: (str, str, Optional[str]) -> Optional[dict]
        """The registry P2P provider behind ``candidate_id``, or None.

        Re-derives from the Registry (never trusts a caller-supplied url):
        a provider is engaged only at the card url its own registration
        published. ``kind`` short-circuits the lookup when the caller
        already knows the candidate is not a provider."""
        if kind is not None and kind != "provider":
            return None
        if not self.registry_url:
            return None
        for candidate in registry_provider_candidates(
            self.registry_url, capability, self.p2p_timeout
        ):
            if candidate["id"] == candidate_id:
                return candidate
        return None

    def rank_candidates(self, candidates):
        # type: (List[dict]) -> List[dict]
        """Order candidates best-first (pure; the input is not mutated).

        Sort keys, in order: ``reputation.verification_rate`` descending
        (no history sorts below any known rate, per RFC-0001 neutral
        reputation), ``reputation.tasks_verified`` descending, then the
        documented tie-breakers ``price`` ascending (unpriced last) and
        ``speed`` ascending (unknown last — lower means faster).
        """

        def sort_key(candidate):
            reputation = candidate.get("reputation") or {}
            rate = reputation.get("verification_rate")
            rate = _NEUTRAL_RATE if rate is None else float(rate)
            verified = reputation.get("tasks_verified") or 0
            price = candidate.get("price")
            price = float("inf") if price is None else float(price)
            speed = candidate.get("speed")
            speed = float("inf") if speed is None else float(speed)
            return (-rate, -verified, price, speed)

        return sorted(candidates, key=sort_key)

    # -- terms (P2P work-discovery/bid flow) -------------------------------

    def request_terms(self, app_id, capability, input=None, kind=None):  # noqa: A002
        # type: (str, str, Optional[dict], Optional[str]) -> dict
        """Ask a candidate app for terms over the signed P2P rails.

        The ecosystem apps expose no dedicated "quote"/"terms" endpoint;
        the closest the rails support (RFC-0003/U10, see
        ``libs.agent_coordination`` and the marketplace app) is the
        work-discovery/bid flow, so this maps onto it:

        * without ``input["task_id"]``: a signed ``list.work_opportunities``
          request — the open work items for ``capability`` the app
          advertises (``{"opportunities": [...]}``).
        * with ``input["task_id"]``: a signed ``get.task_status`` request —
          terms are the ``proposed_terms`` carried on the task's bids
          (``{"terms": [{"agent", "terms", "status"}, ...]}``).

        ``kind`` is the candidate's kind as returned by
        ``discover_candidates``/``rank_candidates`` (``"app"`` or
        ``"agent"``). When it is ``"agent"`` this returns the shared
        :data:`AGENT_CANDIDATE_OUTCOME` explanation as a normal data
        result instead of reaching the coordinator: agent principals
        aren't registered as apps, so
        ``AgentCoordinator.discover_work``/``P2PClient.discover_app``
        would otherwise raise a raw ``AgentCoordinationError``/
        ``P2PError`` for ``app_id`` (R4, KTD3).

        Requests are signed when the tools hold a session, unsigned
        otherwise (the underlying clients' own optional-session pattern).
        Raises :class:`libs.p2p_client.P2PError` subclasses on transport /
        auth failures — the loop surfaces those as tool errors.
        """
        if kind == "agent":
            return {
                "app_id": app_id,
                "capability": capability,
                "opportunities": [],
                "terms": [],
                "outcome": AGENT_CANDIDATE_OUTCOME,
            }
        provider = self._find_provider(app_id, capability, kind)
        if provider is not None:
            validate_provider_input(provider, capability, input or {})
            # P2P provider rail: ask the provider itself for its offer
            # (task.request -> task.offer), directly at its card url.
            offer = provider_request_offer(
                provider["card_url"], capability, input, self.p2p_timeout
            )
            price = offer.get("price")
            currency = offer.get("currency") or ""
            return {
                "app_id": app_id,
                "capability": capability,
                "provider": True,
                "card_url": provider["card_url"],
                "task_id": offer.get("task_id"),
                "opportunities": [],
                "terms": [{
                    "agent": app_id,
                    "terms": ("%s %s" % (price, currency)).strip()
                    if price is not None else None,
                    "status": "offered",
                }],
            }
        if self.coordinator is None:
            raise ValueError(
                "request_terms needs a registry_url or an injected "
                "coordinator"
            )
        p2p_input = input or {}
        task_id = p2p_input.get("task_id")
        if task_id:
            status = self.coordinator.check_bid_status(app_id, task_id)
            task = status.get("task") or {}
            return {
                "app_id": app_id,
                "capability": capability,
                "task_id": task_id,
                "task_status": task.get("status"),
                "terms": [
                    {
                        "agent": bid.get("agent_principal_id"),
                        "terms": bid.get("proposed_terms"),
                        "status": bid.get("status"),
                    }
                    for bid in task.get("bids", [])
                ],
            }
        opportunities = self.coordinator.discover_work(
            app_id, capability_id=capability
        )
        return {
            "app_id": app_id,
            "capability": capability,
            "opportunities": opportunities,
            "terms": [],
        }

    # -- credentials (ALWAYS through the approval gate) --------------------

    def request_credential_access(self, credential_id, cost=None,
                                  details=None):
        # type: (str, Optional[Decimal], Optional[dict]) -> dict
        """Request a vault credential — gated by the U23 approval gate.

        The gate is consulted FIRST (``credential_access:<id>``); only an
        approved decision ever reaches the vault. Every outcome — gate
        denial, missing gate/vault, vault refusal, vault outage — comes
        back as ``{"granted": False, "reason": ...}`` rather than raising
        into the agent loop. On success the vault's response body (the
        DEK-encrypted ciphertext envelope; the orchestrator never sees
        plaintext) rides along as ``vault_response``.
        """
        if self.gate is None:
            return {
                "granted": False,
                "reason": "no approval gate configured (failing closed)",
            }
        cost = Decimal("0") if cost is None else cost
        tracker = self._outcome
        # Cumulative loop spend (KTD7/R12): when a per-request tracker is
        # live, the gate sees THIS call's cost added to every previously
        # APPROVED cost in the same loop -- not just this call's own cost
        # -- so several individually-small approvals cannot aggregate
        # past ``policy.hard_ceiling`` (which ``ApprovalGate.require``
        # already refuses outright, no callback, once the cost it is
        # handed exceeds the ceiling).
        running_cost = cost if tracker is None else tracker.running_cost + cost
        decision = self.gate.require(
            "credential_access:%s" % credential_id, running_cost, details
        )
        if not decision.approved:
            if tracker is not None:
                tracker.record_declined(decision.reason)
            return {"granted": False, "reason": decision.reason}
        if tracker is not None:
            tracker.running_cost = running_cost
        if self.vault is None:
            return {
                "granted": False,
                "reason": "approved, but no vault is configured",
            }
        try:
            body = self.vault.request_access(
                credential_id, self.agent_principal_id
            )
        except Exception as exc:
            logger.warning(
                "vault access request failed for %s", credential_id,
                exc_info=True,
            )
            return {
                "granted": False,
                "reason": "vault request failed: %s" % exc,
            }
        granted = bool(body.get("access_granted"))
        return {
            "granted": granted,
            "reason": decision.reason if granted
            else "vault denied access (no grant for this agent)",
            "vault_response": body,
        }

    # -- execution (ALWAYS through the approval gate) -----------------------

    def execute_work(self, app_id, capability, cost, details=None):
        # type: (str, str, Decimal, Optional[dict]) -> dict
        """Gated: submit a real, signed work bid (U5, KTD1/KTD6).

        Unlike ``request_terms`` (which accepts an explicit ``task_id``
        from the caller), this takes NO ``task_id``: the model does not
        supply the execution target directly. It re-derives the
        candidate's kind itself (via ``discover_candidates``) and its own
        open opportunity itself (via ``coordinator.discover_work``)
        before ever asking the gate to authorize anything, so an
        untrusted model tool-call cannot point a signed bid at a target
        this request's own discovery never surfaced.

        Only once a real, self-discovered opportunity is confirmed to
        exist does the gate get consulted
        (``execute:<capability>@<app_id>``). Everything else -- a missing
        gate/coordinator rail, an agent-kind candidate, no open work, a
        gate denial, or a rail failure while re-deriving/bidding on the
        opportunity -- comes back as ``{"executed": False, ...}`` data,
        never an exception, mirroring ``request_credential_access``'s own
        failure handling.

        The actual bid submission shares its implementation with the
        deterministic path's ``OrchestratorAgent._execute`` via the
        module-level :func:`submit_work_bid` helper -- ONE
        implementation, not two hand-synced copies.
        """
        if self.gate is None:
            return {
                "executed": False,
                "reason": "no approval gate configured (failing closed)",
            }
        if self.coordinator is None:
            return {
                "executed": False,
                "outcome": "no coordinator rail configured; nothing was "
                "executed",
            }
        candidates = self.discover_candidates(capability)
        candidate = next(
            (c for c in candidates if c.get("id") == app_id), None,
        )
        if candidate is None:
            # Fail closed rather than fabricate a candidate: an app_id
            # this request's own discovery never surfaced must never
            # reach discover_work/submit_bid, or a hallucinated/
            # prompt-injected app_id could point a real signed bid at an
            # unverified target (the exact thing this method's
            # self-grounding is meant to prevent).
            return {
                "executed": False,
                "outcome": "%s no aparece entre los candidatos "
                "descubiertos para %s; nada fue ejecutado"
                % (app_id, capability),
            }
        if candidate.get("kind") == "agent":
            return {"executed": False, "outcome": AGENT_CANDIDATE_OUTCOME}
        if candidate.get("kind") == "provider":
            # P2P provider rail: negotiate directly at the provider's own
            # registered card url — offer first, gate on the REAL offered
            # price, then accept.
            try:
                validate_provider_input(candidate, capability, details or {})
                offer = provider_request_offer(
                    candidate["card_url"], capability, details or {},
                    self.p2p_timeout,
                )
            except (requests.RequestException, P2PError) as exc:
                return {"executed": False, "reason": str(exc)}
            try:
                offered = Decimal(str(offer.get("price")))
            except (InvalidOperation, TypeError, ValueError):
                offered = None
            cost = offered if offered is not None else (
                Decimal("0") if cost is None else cost
            )
            tracker = self._outcome
            running_cost = (
                cost if tracker is None else tracker.running_cost + cost
            )
            decision = self.gate.require(
                "execute:%s@%s" % (capability, app_id), running_cost,
                {"candidate": app_id, "capability": capability,
                 "offer": offer.get("price")},
            )
            if not decision.approved:
                if tracker is not None:
                    tracker.record_declined(decision.reason)
                return {"executed": False, "reason": decision.reason}
            if tracker is not None:
                tracker.running_cost = running_cost
            try:
                result = provider_accept(
                    candidate["card_url"], offer.get("task_id"),
                    self.p2p_timeout, action_broker=self.action_broker,
                )
            except (requests.RequestException, P2PError) as exc:
                return {"executed": False, "reason": str(exc)}
            if result.get("broker_status") in (
                "executing",
                "execution_unknown",
            ):
                return {
                    "executed": False,
                    "pending": True,
                    "outcome": (
                        "No pude confirmar todavía si la acción se completó. "
                        "La estoy verificando."
                    ),
                    "result": result,
                }
            outcome = (
                "trabajo completado por %s a %s %s"
                % (candidate.get("name", app_id), offer.get("price"),
                   offer.get("currency", ""))
            ).strip()
            if tracker is not None:
                tracker.record_executed(outcome, app_id=app_id)
            return {
                "executed": True,
                "outcome": outcome,
                "result": result,
            }
        try:
            opportunities = self.coordinator.discover_work(
                app_id, capability_id=capability
            )
        except (AgentCoordinationError, P2PError) as exc:
            logger.warning(
                "work discovery failed for %s (%s)", app_id, capability,
                exc_info=True,
            )
            return {"executed": False, "reason": str(exc)}
        if not opportunities:
            return {
                "executed": False,
                "outcome": "no hay trabajo abierto en %s por ahora"
                % app_id,
            }
        # The model's claimed cost is a proposal, not authorization (R6
        # defense in depth, mirrored here): an unparseable/absent cost
        # never silently auto-approves.
        cost = Decimal("0") if cost is None else cost
        tracker = self._outcome
        # Cumulative loop spend (KTD7/R12) -- see the identical comment in
        # request_credential_access: the gate is handed the running total
        # across this loop, not just this call's own cost.
        running_cost = cost if tracker is None else tracker.running_cost + cost
        decision = self.gate.require(
            "execute:%s@%s" % (capability, app_id), running_cost, details
        )
        if not decision.approved:
            if tracker is not None:
                tracker.record_declined(decision.reason)
            return {"executed": False, "reason": decision.reason}
        if tracker is not None:
            tracker.running_cost = running_cost
        result = submit_work_bid(
            self.coordinator, candidate, opportunities,
            self.agent_principal_id,
        )
        if tracker is not None and result.get("executed"):
            tracker.record_executed(result.get("outcome"), app_id=app_id)
        return result

    # -- progress surface --------------------------------------------------

    def report_to_user(self, message):
        # type: (str) -> dict
        """Surface a progress/outcome message through the reporter hook."""
        self.reporter(message)
        return {"reported": True, "message": message}

    # -- bounded multi-step collaboration ---------------------------------

    def plan_subtasks(self, subtasks, max_subtasks=5):
        return plan_subtasks(subtasks, max_subtasks=max_subtasks)

    def execute_chain(self, chain_id, subtasks, executor):
        return self._chain_executor.execute(chain_id, subtasks, executor)

    def continue_task(self, agent_id, card_url, envelope):
        """Deliver a prepared ``task.continue`` to the selected agent."""
        if not isinstance(agent_id, str) or not agent_id:
            raise ValueError("agent_id is required")
        if not isinstance(envelope, dict) or envelope.get("type") != "task.continue":
            raise ValueError("a task.continue envelope is required")
        for field in ("task_id", "conversation_id", "idempotency_key"):
            if not isinstance(envelope.get(field), str) or not envelope[field]:
                raise ValueError("%s is required" % field)
        if not isinstance(envelope.get("resolved_fields"), dict):
            raise ValueError("resolved_fields must be an object")
        return _a2a_send(card_url, envelope, self.p2p_timeout)


# -- Tool-Runner exposure ----------------------------------------------------


def build_beta_tools(tools):
    # type: (OrchestratorTools) -> list
    """Thin ``@beta_tool`` wrappers (closures over ``tools``) for the
    Anthropic Tool Runner.

    Each wrapper validates its inputs, delegates to the corresponding
    :class:`OrchestratorTools` method (the ONE implementation shared with
    direct callers), and returns a JSON string — always serializable, so
    tool results flow cleanly back into the model loop. Schemas are
    generated by the SDK from the signatures and the ``Args:`` sections.
    """

    def _dumps(value):
        return json.dumps(value, ensure_ascii=False, default=str)

    @beta_tool
    def discover_candidates(capability: str) -> str:
        """Discover apps and agents in the ecosystem that offer a capability.

        Args:
            capability: Capability id to search for, e.g. "marketplace.tasks".
        """
        result = tools.discover_candidates(capability)
        # Reads the CURRENT tracker at call time (an attribute lookup on
        # `tools`, KTD2) -- this closure is cached/request-independent;
        # only the tracker's contents vary per request. An empty result
        # here is the "nothing to offer this request" outcome the
        # precedence rule calls no_candidate, unless something later in
        # the same loop executes or is declined (KTD2 precedence wins).
        tracker = tools._outcome
        if tracker is not None and not result:
            tracker.record_no_candidate()
        return _dumps(result)

    @beta_tool
    def rank_candidates(candidates: List[Dict[str, Any]]) -> str:
        """Rank discovered candidates best-first by reputation, then price and speed.

        Args:
            candidates: Candidate objects as returned by discover_candidates
                (each has id, kind and reputation, optionally price/speed).
        """
        return _dumps(tools.rank_candidates(list(candidates or [])))

    @beta_tool
    def request_terms(
        app_id: str,
        capability: str,
        task_id: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> str:
        """Request terms/cost from a candidate app over the signed P2P rails.

        Args:
            app_id: The candidate app to ask, e.g. "marketplace".
            capability: The capability the work belongs to.
            task_id: Optional task id; when given, returns the terms
                proposed on that task's bids instead of open opportunities.
            kind: The candidate's "kind" field as returned by
                discover_candidates/rank_candidates ("app" or "agent").
                Pass it along when known -- an agent-kind candidate gets
                a courteous explanation back instead of an error, since
                the current rails only execute work inside apps.
        """
        p2p_input = {"task_id": task_id} if task_id else None
        return _dumps(tools.request_terms(app_id, capability, p2p_input, kind))

    @beta_tool
    def request_credential_access(
        credential_id: str, cost: str = "0"
    ) -> str:
        """Request access to a vault credential; requires user approval first.

        Args:
            credential_id: The vault credential id to request access to.
            cost: The spend this access implies, as a decimal string
                (e.g. "2.50"); it is checked against the user's policy.
        """
        cost_decimal = _parse_finite_cost(cost)
        if cost_decimal is None:
            return _dumps({
                "granted": False,
                "reason": "invalid cost %r: must be a decimal string" % cost,
            })
        # The model's claimed cost is a proposal, not authorization (R6
        # defense in depth): never let it slip below the auto-approve
        # threshold on its own say-so — every LLM-path credential request
        # goes to the human/policy callback.
        if tools.gate is not None:
            cost_decimal = max(
                cost_decimal, tools.gate.policy.auto_approve_under
            )
        result = tools.request_credential_access(
            credential_id, cost=cost_decimal
        )
        # The sealed vault envelope must never reach the LLM (R6) — only
        # the granted/denied outcome does. Full result (including
        # vault_response) stays in OrchestratorTools' own return value for
        # direct/RuleBrain callers and the agent's evidence.
        result = dict(result)
        result.pop("vault_response", None)
        return _dumps(result)

    @beta_tool
    def report_to_user(message: str) -> str:
        """Show the user a short progress or outcome message.

        Args:
            message: The courteous, user-facing message to display.
        """
        return _dumps(tools.report_to_user(message))

    return [
        discover_candidates,
        rank_candidates,
        request_terms,
        request_credential_access,
        report_to_user,
    ]


def build_execute_work_tool(tools):
    # type: (OrchestratorTools) -> Any
    """The ``execute_work`` ``@beta_tool`` wrapper (U5), built standalone
    so it exists and is fully testable independent of the Tool Runner's
    actual tool set. ``agents.orchestrator.agent.OrchestratorAgent
    ._get_beta_tools`` (U6) folds this INTO the Tool Runner's tool list by
    appending it to :func:`build_beta_tools`'s own return value, rather
    than changing that function's returned list itself -- keeping
    :func:`build_beta_tools`'s own contract (and tests) exactly as they
    were: the exact 5-tool U22 surface, unaware execute_work exists.

    Mirrors ``request_credential_access``'s wrapper pattern exactly: the
    model's claimed cost is a proposal, never authorization -- it is
    floored at ``tools.gate.policy.auto_approve_under`` so a single call
    can never dodge the gate on its own say-so. The running-total
    cumulative check across multiple calls in one loop (KTD7/R12) lives
    one layer down, in :meth:`OrchestratorTools.execute_work` itself
    (reading ``tools._outcome`` at call time, U6), so both this wrapper
    and direct/RuleBrain callers share the identical cumulative-spend
    protection. The LLM-visible result is a minimal, explicit shape only
    -- ``{"executed": bool, "outcome": str}`` -- never the coordinator's
    raw bid object or a task id (KTD6); the full result (including
    ``task_id``/``bid``) stays available from
    :meth:`OrchestratorTools.execute_work` itself for direct/RuleBrain
    callers and the agent's own evidence.
    """

    def _dumps(value):
        return json.dumps(value, ensure_ascii=False, default=str)

    @beta_tool
    def execute_work(app_id: str, capability: str, cost: str = "0") -> str:
        """Execute real work: submit a signed bid on the best open opportunity you already discovered for this app and capability.

        Args:
            app_id: The candidate app to execute work through, e.g.
                "marketplace" -- one you already discovered via
                discover_candidates for this capability. There is no
                task_id argument: the open opportunity to bid on is
                re-derived here, not supplied by you.
            capability: The capability the work belongs to.
            cost: The spend this execution implies, as a decimal string
                (e.g. "2.50"); it is checked against the user's policy.
        """
        cost_decimal = _parse_finite_cost(cost)
        if cost_decimal is None:
            return _dumps({
                "executed": False,
                "outcome": "invalid cost %r: must be a decimal string"
                % cost,
            })
        # The model's claimed cost is a proposal, not authorization (R6
        # defense in depth, mirrored from request_credential_access):
        # never let it slip below the auto-approve threshold on its own
        # say-so -- every LLM-path execution request goes to the
        # human/policy callback.
        if tools.gate is not None:
            cost_decimal = max(
                cost_decimal, tools.gate.policy.auto_approve_under
            )
        result = tools.execute_work(app_id, capability, cost_decimal)
        # Minimal, explicit LLM-visible shape only (KTD6) -- never the
        # coordinator's raw bid object or a task id. The full result
        # (task_id/bid included) stays in OrchestratorTools.execute_work's
        # own return value for direct callers and the agent's evidence.
        return _dumps({
            "executed": bool(result.get("executed")),
            "outcome": result.get("outcome") or result.get("reason") or "",
        })

    return execute_work
