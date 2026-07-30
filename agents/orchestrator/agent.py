"""Orchestrator concierge agent (unit U24).

Ties the pluggable brain (U21), the bounded tool set (U22) and the
approval gate (U23) into ONE signed agent Principal that takes a
natural-language request and drives the concierge sequence:

    understand -> discover -> rank -> terms -> (approval gate) ->
    execute -> report

:meth:`OrchestratorAgent.handle_request` drives exactly one such
conversation and returns a :class:`Result` — there is no infinite loop;
callers (and tests) invoke it directly, mirroring the step-driven
``single_cycle`` style of ``agents.marketplace_coordinator.agent``.

Two driving modes share the SAME U22 tool implementations:

* With a :class:`~agents.orchestrator.brain.ClaudeBrain`, the
  discover/rank/terms/(credential)/execute middle is driven by the
  Anthropic Tool Runner (``client.beta.messages.tool_runner``) over
  ``_get_beta_tools()`` (the U22 5-tool set plus the gated U5
  ``execute_work`` tool, U6) with a bounded ``max_iterations``. The
  model's action surface is EXACTLY that bounded tool set — every
  spend/credential/execution-bearing tool in it is already gated inside
  ``OrchestratorTools``, so no runner iteration can spend or execute
  outside the user's policy. A per-request outcome tracker
  (``tools._outcome``, U6) records what actually happened so
  ``Result.status`` reflects it honestly instead of always claiming
  "done". The client is the brain's (injectable), so the whole path
  runs against a scripted fake with no network.
* With any other brain (:class:`~agents.orchestrator.brain.RuleBrain`),
  the agent calls the same tool methods directly in the fixed sequence
  above, gating the execution spend explicitly before anything runs.

Execution choice (documented per the plan): the ecosystem apps expose no
one-shot "execute" endpoint. The minimal real execution the marketplace
rails support (RFC-0003/U10 — the exact flow
``MarketplaceCoordinatorAgent`` drives and ``request_terms`` derives its
answers from) is submitting a work bid on the top open opportunity via
``AgentCoordinator.submit_bid``. That is what the deterministic path
does after approval; when there is nothing biddable (agent candidate,
no open work, no coordinator rail) the outcome says so and the
conversation still completes courteously.

Credential hygiene (R6): the brain NEVER sees credential material. When
a credential is needed (an explicit ``credential_id`` constructor arg or
``intent.params["credential_id"]``), the agent calls the gated U22
``request_credential_access`` itself and only a ``granted`` boolean ever
reaches brain inputs/state — the sealed vault envelope stays inside the
agent's evidence.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

import requests

from agents.orchestrator.brain import (
    KNOWN_CAPABILITIES,
    ClaudeBrain,
    Intent,
)
from agents.orchestrator.tools import (
    AGENT_CANDIDATE_OUTCOME,
    OutcomeTracker,
    build_beta_tools,
    build_execute_work_tool,
    provider_accept,
    submit_work_bid,
)

logger = logging.getLogger(__name__)

DEFAULT_AGENT_ID = "agent:orchestrator"
DEFAULT_CREATED_BY = "user:orchestrator-operator"
DEFAULT_HTTP_TIMEOUT = 5.0
#: Upper bound on Tool-Runner iterations in the ClaudeBrain path.
DEFAULT_MAX_ITERATIONS = 8
DEFAULT_CANDIDATES_TO_EVALUATE = 3
NO_CANDIDATE_REPLY = (
    "No encontré un agente disponible. No se realizó ningún cargo."
)

_RUNNER_SYSTEM = (
    "You are the chief operating officer for an agent ecosystem, acting on "
    "behalf of the user. The intent-analysis phase already confirmed that "
    "the request is ready for discovery. Use evidence, not instinct: discover "
    "real candidates for the exact capability, rank them, compare terms from "
    "the strongest viable alternatives, and choose the candidate that best "
    "fits the user's constraints and preferences. Never invent a candidate, "
    "capability, price, credential, or successful outcome. Only "
    "request_credential_access if the work truly needs a credential — "
    "it requires the user's approval. Once terms are known (and any "
    "needed credential access has been granted), call execute_work to "
    "actually commit the work as a signed bid — nothing is executed "
    "until you call it. Use report_to_user for progress. Finish with a "
    "short, courteous summary in the user's language."
)

#: First decimal number inside free-text terms, e.g. "2 credits, today".
_MONEY_RE = re.compile(r"\d+(?:\.\d+)?")


@dataclass
class Result:
    """Outcome of one full :meth:`OrchestratorAgent.handle_request`."""

    status: str  # "done" | "needs_clarification" | "no_candidate"
    #             | "declined" | "failed"
    reply: str
    evidence: Dict[str, Any] = field(default_factory=dict)


# -- cost derivation ---------------------------------------------------------


def _parse_money(value):
    # type: (object) -> Optional[Decimal]
    """Best-effort Decimal out of a terms value; None when unparseable."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # Never build money straight from float bits.
        return Decimal(str(value))
    if isinstance(value, dict):
        for key in ("cost", "price", "amount"):
            if key in value:
                return _parse_money(value[key])
        return None
    if isinstance(value, str):
        match = _MONEY_RE.search(value)
        if match:
            try:
                return Decimal(match.group(0))
            except InvalidOperation:  # pragma: no cover - regex-safe
                return None
    return None


def derive_cost(terms_result):
    # type: (dict) -> Optional[Decimal]
    """Cost implied by a ``request_terms`` result, or ``None``.

    First parseable value wins: the ``proposed_terms`` carried on bids
    (best-ranked first), then any ``cost``/``price``/``budget`` field on
    the open opportunities. An explicit, parseable zero-cost term (e.g.
    ``"0 credits"``) legitimately returns ``Decimal("0")`` — that case is
    genuinely free and unaffected by the caller's fallback handling.

    When NOTHING parseable is found anywhere in the terms, this returns
    ``None`` rather than ``Decimal("0")`` (R5, KTD4): conflating "found an
    explicit zero" with "found nothing at all" would let unparseable-cost
    work silently masquerade as free and auto-approve whenever the
    operator's ``auto_approve_under`` threshold is above zero. Callers
    MUST treat ``None`` as "cost unknown" and floor it at (or above) the
    gate's ``auto_approve_under`` before calling ``gate.require``, so the
    approval callback is always consulted for unknown-cost work —
    mirroring the identical floor already applied to the LLM-supplied
    cost in ``agents/orchestrator/tools.py``'s ``request_credential_access``
    wrapper.
    """
    terms_result = terms_result or {}
    for entry in terms_result.get("terms") or []:
        value = _parse_money((entry or {}).get("terms"))
        if value is not None:
            return value
    for opportunity in terms_result.get("opportunities") or []:
        for key in ("cost", "price", "budget"):
            if key in (opportunity or {}):
                value = _parse_money(opportunity[key])
                if value is not None:
                    return value
    return None


class OrchestratorAgent(object):
    """The concierge: one signed Principal over brain + tools + gate."""

    def __init__(
        self,
        registry_url,
        brain,
        tools,
        gate,
        session=None,
        agent_id=DEFAULT_AGENT_ID,
        created_by=DEFAULT_CREATED_BY,
        credential_id=None,
        http_timeout=DEFAULT_HTTP_TIMEOUT,
        max_iterations=DEFAULT_MAX_ITERATIONS,
        candidates_to_evaluate=DEFAULT_CANDIDATES_TO_EVALUATE,
    ):
        # type: (...) -> None
        if not registry_url:
            raise ValueError("registry_url is required")
        if brain is None:
            raise ValueError("brain is required")
        if tools is None:
            raise ValueError("tools is required")
        if gate is None:
            raise ValueError("gate is required")
        self.registry_url = registry_url.rstrip("/")
        self.brain = brain
        self.tools = tools
        self.gate = gate
        self.session = session
        self.agent_id = agent_id
        self.created_by = created_by
        #: Optional credential this agent's plans need; may also arrive
        #: per-request as ``intent.params["credential_id"]``.
        self.credential_id = credential_id
        self.http_timeout = http_timeout
        self.max_iterations = max_iterations
        self.candidates_to_evaluate = max(1, int(candidates_to_evaluate))
        # Tool-Runner definitions are request-independent; build once per
        # tools instance instead of on every handle_request call.
        self._beta_tools_cache = None
        self._beta_tools_for = None

    def _get_beta_tools(self):
        # type: () -> list
        """The Tool Runner's full tool list: the cached U22 5-tool set
        (``build_beta_tools``) plus the gated ``execute_work`` tool (U5),
        folded in here (U6) rather than into ``build_beta_tools``'s own
        returned list, so that function's contract (and its own tests)
        stay exactly as they were. Still built once per ``tools``
        instance, not per request (U21-U26, commit ``46ce3b7``): these
        closures are request-independent, they only ever read the
        per-request outcome tracker's CURRENT value (an attribute lookup
        on ``self.tools``) at call time.
        """
        if self._beta_tools_cache is None or self._beta_tools_for is not self.tools:
            self._beta_tools_for = self.tools
            self._beta_tools_cache = build_beta_tools(self.tools) + [
                build_execute_work_tool(self.tools),
            ]
        return self._beta_tools_cache

    # -- registry registration (U5, mirrors MarketplaceCoordinatorAgent) ----

    def register(self):
        # type: () -> bool
        """Register this agent as a Principal in the Registry. Idempotent:
        an already-registered agent (409) counts as success.

        When the agent holds a session, the registration rides the same
        rail the Registry already supports for secure mode: the body
        carries the principal's ``public_key`` (MVP convention: the
        session's principal_id IS the base64 public key) and the request
        is signed with the session's ``X-AT-*`` headers. Without a
        session the request is byte-for-byte the marketplace
        coordinator's plain registration.
        """
        payload = {
            "principal_id": self.agent_id,
            "created_by": self.created_by,
            "agent_card": {
                "name": self.agent_id,
                "description": "LLM-driven concierge orchestrator agent "
                "(U24)",
                "capabilities": list(KNOWN_CAPABILITIES),
            },
        }
        headers = {"Content-Type": "application/json"}
        if self.session is not None:
            payload["public_key"] = self.session.principal_id
        body = json.dumps(payload).encode("utf-8")
        if self.session is not None:
            headers.update(
                self.session.auth_headers("POST", "/agents/register", body)
            )
        try:
            resp = requests.post(
                "%s/agents/register" % self.registry_url,
                data=body,
                headers=headers,
                timeout=self.http_timeout,
            )
        except requests.RequestException:
            return False
        return resp.status_code in (200, 409)

    # -- the concierge conversation -----------------------------------------

    def handle_request(self, nl_request, context=None):
        # type: (str, Optional[dict]) -> Result
        """Drive ONE full concierge conversation for ``nl_request``."""
        try:
            intent = self.brain.understand(nl_request, context)
        except Exception as exc:
            logger.warning("brain failed to parse request", exc_info=True)
            return Result(
                status="failed",
                reply="Lo siento, no pude procesar su solicitud en este "
                "momento.",
                evidence={"error": str(exc)},
            )

        # Social, memory, and cancel turns are conversation, not latent
        # authorization to replay the last understood request.
        if intent.conversation_act in (
            "social", "conversation", "memory", "cancel",
        ):
            status = (
                "cancelled"
                if intent.conversation_act == "cancel"
                else "conversation"
            )
            reply = intent.user_message
            converse = getattr(self.brain, "converse", None)
            if callable(converse) and intent.conversation_act != "cancel":
                try:
                    reply = converse(nl_request, context)
                except Exception:
                    logger.warning(
                        "brain failed to continue conversation",
                        exc_info=True,
                    )
            return Result(
                status=status,
                reply=reply or (
                    "Entendido." if status == "cancelled"
                    else "Con gusto. ¿En qué más puedo ayudarte?"
                ),
                evidence={"intent": intent.model_dump()},
            )

        # 1. Clarify BEFORE any discovery or spend. Readiness is explicit in
        # the richer intent model: a model cannot trigger search merely by
        # emitting a capability while also admitting that a blocker remains.
        if not intent.can_search():
            questions = intent.missing_info or [
                "¿Cuál es el resultado concreto que quieres conseguir?"
            ]
            return Result(
                status="needs_clarification",
                reply=questions[0],
                evidence={"intent": intent.model_dump()},
            )

        try:
            if isinstance(self.brain, ClaudeBrain):
                return self._handle_with_tool_runner(nl_request, intent)
            return self._handle_stepwise(intent)
        except Exception as exc:
            logger.warning(
                "orchestration failed for capability %r",
                intent.capability, exc_info=True,
            )
            return Result(
                status="failed",
                reply="Lo siento, ocurrió un problema al atender su "
                "solicitud. Ningún cargo fue realizado sin su aprobación.",
                evidence={"error": str(exc), "capability": intent.capability},
            )

    # -- deterministic path (RuleBrain): fixed tool sequence -----------------

    def _handle_stepwise(self, intent):
        # type: (Intent) -> Result
        capability = intent.capability

        # 2. Discover.
        candidates = self.tools.discover_candidates(capability)
        if not candidates:
            return Result(
                status="no_candidate",
                reply=NO_CANDIDATE_REPLY,
                evidence={"capability": capability, "candidates": []},
            )

        # 3. Rank, then investigate several viable alternatives. Ranking is
        # only a shortlist; terms are real evidence. This avoids committing to
        # the first reputable-looking candidate before discovering that it has
        # no actionable work or violates an explicit user preference.
        ranked = self.tools.rank_candidates(candidates)
        engageable = [candidate for candidate in ranked
                      if candidate.get("kind") != "agent"]
        if not engageable:
            reply = self.brain.compose_reply({
                "status": "failed",
                "outcome": AGENT_CANDIDATE_OUTCOME,
            })
            return Result(
                status="failed",
                reply=reply,
                evidence={
                    "capability": capability,
                    "candidates": ranked,
                    "error": AGENT_CANDIDATE_OUTCOME,
                },
            )

        evaluations = self._evaluate_candidates(
            engageable, capability, intent,
        )
        if not evaluations:
            reply = self.brain.compose_reply({
                "status": "failed",
                "outcome": "encontré candidatos, pero ninguno respondió con "
                "términos utilizables; no se ejecutó nada",
            })
            return Result(
                status="failed",
                reply=reply,
                evidence={"capability": capability, "candidates": ranked},
            )

        selected = self._select_evaluation(evaluations, intent)
        top = selected["candidate"]
        terms = selected["terms"]
        cost = selected["cost"]
        if cost is None:
            # Nothing parseable anywhere in the terms (R5, KTD4): this is
            # NOT the same as an explicit, parsed zero-cost term, so it
            # must never silently auto-approve. Floor it at the policy's
            # auto-approve threshold so the gate's callback is always
            # consulted — mirroring the identical floor already applied
            # to the LLM-supplied cost in tools.py's
            # request_credential_access wrapper.
            cost = self.gate.policy.auto_approve_under

        # 5. EVERY execution passes the gate, even at zero cost.
        action = "execute:%s@%s" % (capability, top["id"])
        details = {
            "candidate": top["id"],
            "capability": capability,
            "params": intent.params,
            "constraints": intent.constraints,
            "preferences": intent.preferences,
        }
        decision = self.gate.require(action, cost, details)
        if not decision.approved:
            reply = self.brain.compose_reply({
                "status": "declined",
                "outcome": decision.reason,
            })
            return Result(
                status="declined",
                reply=reply,
                evidence={
                    "candidate": top,
                    "cost": str(cost),
                    "decision": {"approved": False,
                                 "reason": decision.reason},
                },
            )

        evidence = {
            "candidate": top,
            "cost": str(cost),
            "decision": {"approved": True, "reason": decision.reason},
            "evaluated_candidates": [
                {
                    "id": item["candidate"].get("id"),
                    "cost": (
                        str(item["cost"])
                        if item["cost"] is not None else None
                    ),
                    "actionable": item["actionable"],
                }
                for item in evaluations
            ],
        }

        # 6a. Credential, if the plan needs one — the agent consumes the
        # sealed result itself; the brain only ever sees a boolean (R6).
        credential_id = self.credential_id or (
            intent.params or {}
        ).get("credential_id")
        credential_granted = None
        if credential_id:
            access = self.tools.request_credential_access(
                credential_id, details=details
            )
            credential_granted = bool(access.get("granted"))
            evidence["credential"] = {
                "credential_id": credential_id,
                "granted": credential_granted,
            }
            if not credential_granted:
                reply = self.brain.compose_reply({
                    "status": "failed",
                    "outcome": "el acceso a la credencial necesaria no fue "
                    "autorizado; no se ejecutó el trabajo",
                })
                return Result(
                    status="failed", reply=reply, evidence=evidence,
                )

        # 6b. Execute over the signed rails (see module docstring).
        execution = self._execute(top, terms)
        evidence["execution"] = execution

        # 7. Compose + surface the reply.
        execution_status = "done" if execution.get("executed") else "failed"
        state = {
            "status": execution_status,
            "capability": capability,
            "candidate": top["id"],
            "cost": str(cost),
            "outcome": execution.get("outcome"),
        }
        if credential_granted is not None:
            state["credential_granted"] = credential_granted
        reply = self.brain.compose_reply(state)
        self.tools.report_to_user(reply)
        return Result(status=execution_status, reply=reply, evidence=evidence)

    def _evaluate_candidates(self, ranked, capability, intent):
        # type: (List[dict], str, Intent) -> List[dict]
        """Collect comparable, bounded evidence from the best candidates."""
        evaluations = []
        for candidate in ranked[:self.candidates_to_evaluate]:
            try:
                terms = self.tools.request_terms(
                    candidate["id"], capability, intent.params or None
                )
            except Exception as exc:
                logger.warning(
                    "candidate %s did not return terms",
                    candidate.get("id"), exc_info=True,
                )
                evaluations.append({
                    "candidate": candidate,
                    "terms": {},
                    "cost": None,
                    "actionable": False,
                    "error": str(exc),
                })
                continue
            actionable = bool(
                (terms.get("provider") and terms.get("card_url")
                 and terms.get("task_id"))
                or terms.get("opportunities")
            )
            evaluations.append({
                "candidate": candidate,
                "terms": terms,
                "cost": derive_cost(terms),
                "actionable": actionable,
            })
        # Keep failures in evidence only when every candidate failed. If at
        # least one candidate is actionable, never choose a dead alternative.
        actionable = [item for item in evaluations if item["actionable"]]
        return actionable or [
            item for item in evaluations if item.get("terms")
        ]

    @staticmethod
    def _select_evaluation(evaluations, intent):
        # type: (List[dict], Intent) -> dict
        """Choose from grounded terms according to the user's preference."""
        priority = (intent.preferences or {}).get("priority")
        if priority == "lowest_cost":
            priced = [item for item in evaluations if item["cost"] is not None]
            if priced:
                return min(priced, key=lambda item: item["cost"])
        if priority == "fastest":
            with_speed = [
                item for item in evaluations
                if item["candidate"].get("speed") is not None
            ]
            if with_speed:
                return min(
                    with_speed,
                    key=lambda item: float(item["candidate"]["speed"]),
                )
        # Reputation ordering from rank_candidates remains the default and
        # also implements an explicit highest_reputation preference.
        return evaluations[0]

    def _execute(self, candidate, terms):
        # type: (dict, dict) -> dict
        """Minimal real execution the marketplace rails support: submit a
        signed work bid on the top open opportunity (RFC-0003/U10 — the
        same ``AgentCoordinator`` flow ``request_terms`` derives its
        terms from). Anything non-biddable completes with an explanatory
        outcome instead of an invented endpoint.

        Delegates the actual bid-submission core to the module-level
        ``submit_work_bid`` helper in ``agents.orchestrator.tools`` — the
        SAME implementation the tool-runner path's gated
        ``OrchestratorTools.execute_work`` uses (U5, KTD6), so the two
        driving paths can never drift into hand-synced copies.
        """
        if candidate.get("kind") == "provider" or terms.get("provider"):
            # P2P provider rail: close the negotiation the terms opened —
            # task.accept at the provider's registered card url. ONE shared
            # implementation (tools.provider_accept) with the tool-runner path.
            card_url = terms.get("card_url")
            task_id = terms.get("task_id")
            if not card_url or not task_id:
                return {
                    "executed": False,
                    "outcome": "el proveedor no entregó una oferta usable; "
                    "nada fue ejecutado",
                }
            try:
                result = provider_accept(
                    card_url, task_id, self.tools.p2p_timeout,
                    action_broker=self.tools.action_broker,
                )
            except Exception as exc:
                return {"executed": False, "outcome": str(exc)}
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
            price = None
            for entry in terms.get("terms") or []:
                price = (entry or {}).get("terms") or price
            outcome = "trabajo completado por %s%s" % (
                candidate.get("name", candidate.get("id")),
                " a %s" % price if price else "",
            )
            return {"executed": True, "outcome": outcome, "result": result}
        coordinator = getattr(self.tools, "coordinator", None)
        opportunities = terms.get("opportunities") or []
        return submit_work_bid(
            coordinator, candidate, opportunities, self.agent_id
        )

    # -- LLM-driven path (ClaudeBrain): Anthropic Tool Runner ----------------

    def _handle_with_tool_runner(self, nl_request, intent):
        # type: (str, Intent) -> Result
        """Let Claude drive discover/rank/terms/(credential)/execute/report
        over the bounded U22+U5 tool set. Spend/credential safety holds
        structurally: the ONLY spend-bearing tools exposed are
        ``request_credential_access`` and ``execute_work``, and both are
        gated inside ``OrchestratorTools`` -- the runner has no raw
        payment or execution primitive outside that set.

        ``tools._outcome`` (U6, KTD2/KTD7) is reset to a fresh
        :class:`OutcomeTracker` immediately before the loop runs -- NOT
        baked into ``_get_beta_tools``'s cached closures, which stay
        request-independent -- and read once after the loop ends to
        derive an honest ``Result.status`` per KTD2's explicit
        precedence: ``done`` > ``declined`` > ``no_candidate`` >
        ``failed``.
        """
        prompt = (
            "Solicitud del usuario: %s\n\nIntent estructurado:\n%s"
            % (
                nl_request,
                json.dumps(
                    intent.model_dump(), ensure_ascii=False, sort_keys=True
                ),
            )
        )
        self.tools._outcome = OutcomeTracker()
        reply, iterations = self.brain.run_tool_loop(
            prompt,
            tools=self._get_beta_tools(),
            system=_RUNNER_SYSTEM,
            max_iterations=self.max_iterations,
        )
        tracker = self.tools._outcome
        status = tracker.status()
        evidence = {
            "path": "tool_runner",
            "iterations": iterations,
            "capability": intent.capability,
        }
        if status == "done":
            evidence["execution"] = {
                "outcome": tracker.executed_outcome,
                "candidate": tracker.executed_app_id,
                "cost": str(tracker.running_cost),
            }
        elif status == "declined":
            evidence["decision"] = {
                "approved": False, "reason": tracker.declined_reason,
            }
        if status == "no_candidate":
            # Keep this common dead end direct and useful. Do not let a
            # language model expand it into a letter or generic pleasantries.
            reply = NO_CANDIDATE_REPLY
        if not reply:
            # The loop ended with no synthesized final text (e.g.
            # max_iterations exhausted, or the model stopped after a
            # tool call with nothing to say) -- compose an honest reply
            # from the SAME state shape the deterministic path uses,
            # never a fabricated "done".
            state = {"status": status, "capability": intent.capability}
            if status == "done":
                state["outcome"] = tracker.executed_outcome
            elif status == "declined":
                state["outcome"] = tracker.declined_reason
            reply = self.brain.compose_reply(state)
        return Result(status=status, reply=reply, evidence=evidence)
