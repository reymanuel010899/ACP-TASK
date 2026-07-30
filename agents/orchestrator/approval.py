"""Approval gate + spend policy for the orchestrator agent (unit U23).

The safety spine of the orchestrator: NO spend or credential use happens
without passing :meth:`ApprovalGate.require`. The user sets the limits via
:class:`SpendPolicy`; the code enforces them:

* ``cost > hard_ceiling``       -> refused OUTRIGHT. The callback is never
  consulted — the ceiling wins even over an always-approve callback.
* ``cost < auto_approve_under`` -> approved silently, callback not called.
* otherwise                     -> the human (or configured callback) decides.

Boundary semantics are STRICT on both ends, deliberately conservative:

* ``cost == auto_approve_under`` is NOT auto-approved — it goes to the
  callback (auto-approval requires strictly less).
* ``cost == hard_ceiling`` is NOT refused — spending exactly the user's
  ceiling is allowed, subject to the callback (refusal requires strictly
  more).

All money is :class:`decimal.Decimal` — floats are rejected with
``TypeError`` so rounding bugs can never approve a spend.

Every decision is logged (stdlib ``logging``) and, when an audit URL is
configured, emitted to the central Audit & Compliance service via
``libs.audit_client`` (same pattern as the other services). Audit is
best-effort by contract: a dead/broken sink never breaks the gate.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Optional

from libs.audit_client import make_audit_client

logger = logging.getLogger(__name__)

DEFAULT_PRINCIPAL_ID = "agent:orchestrator"
AUDIT_ACTIVITY_TYPE = "orchestrator.approval_decision"

# Answers cli_prompt_callback accepts as approval (English + Spanish).
# ANYTHING else — including empty input — denies: safe default.
_APPROVE_ANSWERS = frozenset(("y", "yes", "s", "si"))
_DENY_ANSWERS = frozenset(("n", "no"))

SIDE_EFFECTING_CAPABILITIES = frozenset(
    ("calendar.create", "gmail.send", "drive.upload")
)


def requires_action_approval(capability_id):
    """Side effects always require payload approval, even when cost is zero."""
    return capability_id in SIDE_EFFECTING_CAPABILITIES


def _require_decimal(name, value):
    # type: (str, object) -> Decimal
    """Money must be Decimal, NEVER float (or anything else)."""
    if not isinstance(value, Decimal):
        raise TypeError(
            "%s must be a decimal.Decimal, got %s (money is never a float)"
            % (name, type(value).__name__)
        )
    return value


@dataclass(frozen=True)
class SpendPolicy:
    """User-set spending limits, enforced in code by :class:`ApprovalGate`.

    ``auto_approve_under``: spends strictly below this are approved without
    asking. ``hard_ceiling``: spends strictly above this are refused without
    asking — no callback can override it.
    """

    auto_approve_under: Decimal
    hard_ceiling: Decimal

    def __post_init__(self):
        # type: () -> None
        _require_decimal("auto_approve_under", self.auto_approve_under)
        _require_decimal("hard_ceiling", self.hard_ceiling)
        if self.hard_ceiling < self.auto_approve_under:
            raise ValueError(
                "hard_ceiling (%s) must not be below auto_approve_under (%s)"
                % (self.hard_ceiling, self.auto_approve_under)
            )


@dataclass(frozen=True)
class Decision:
    """One auditable approval decision."""

    approved: bool
    reason: str


class ApprovalGate:
    """Human-in-the-loop gate every spend/credential use must pass.

    ``approval_callback(action, cost, details) -> bool`` is consulted only
    for costs in the gray zone between the policy's two thresholds. Pass
    :func:`cli_prompt_callback` for an interactive gate,
    :func:`auto_deny_callback` for a locked-down one.

    ``audit_client`` may be injected directly (any object with the
    ``libs.audit_client`` ``log`` signature); otherwise one is built from
    ``audit_url`` — a no-op client when no URL is configured.
    """

    def __init__(self, policy, approval_callback, audit_url=None,
                 principal_id=DEFAULT_PRINCIPAL_ID, audit_client=None):
        # type: (SpendPolicy, Callable, Optional[str], str, Optional[object]) -> None
        if not isinstance(policy, SpendPolicy):
            raise TypeError("policy must be a SpendPolicy")
        if not callable(approval_callback):
            raise TypeError("approval_callback must be callable")
        self.policy = policy
        self.approval_callback = approval_callback
        self.principal_id = principal_id
        self.audit_client = (
            audit_client if audit_client is not None
            else make_audit_client(audit_url)
        )

    def require(self, action, cost, details=None):
        # type: (str, Decimal, Optional[dict]) -> Decision
        """Decide whether ``action`` costing ``cost`` may proceed.

        Never raises for a policy outcome — callers branch on the returned
        :class:`Decision`. Raises ``TypeError`` only for non-Decimal money
        (a programming error, not a policy decision).
        """
        _require_decimal("cost", cost)
        policy = self.policy

        if cost > policy.hard_ceiling:
            # Ceiling wins over EVERYTHING: no callback, no override.
            decision = Decision(
                approved=False,
                reason=(
                    "refused: cost %s exceeds the hard ceiling of %s"
                    % (cost, policy.hard_ceiling)
                ),
            )
        elif cost < policy.auto_approve_under:
            decision = Decision(
                approved=True,
                reason=(
                    "auto-approved: cost %s is below the auto-approve "
                    "threshold of %s" % (cost, policy.auto_approve_under)
                ),
            )
        else:
            approved = bool(self.approval_callback(action, cost, details))
            if approved:
                decision = Decision(
                    approved=True,
                    reason="approved by approval callback for cost %s" % cost,
                )
            else:
                decision = Decision(
                    approved=False,
                    reason=(
                        "denied by approval callback (user or policy "
                        "declined) for cost %s" % cost
                    ),
                )

        self._record(action, cost, details, decision)
        return decision

    # -- decision audit trail ----------------------------------------------

    def _record(self, action, cost, details, decision):
        # type: (str, Decimal, Optional[dict], Decision) -> None
        """Log + emit one decision, best-effort: never breaks the gate."""
        status = "approved" if decision.approved else "denied"
        logger.info(
            "approval decision: action=%s cost=%s status=%s reason=%s",
            action, cost, status, decision.reason,
        )
        audit_details = {
            "cost": str(cost),
            "reason": decision.reason,
        }
        if details is not None:
            audit_details["request_details"] = details
        try:
            self.audit_client.log(
                self.principal_id,
                AUDIT_ACTIVITY_TYPE,
                resource_id=action,
                status=status,
                details=audit_details,
            )
        except Exception:
            # Audit is an observability side channel, never a dependency
            # (same contract as libs.audit_client): a broken sink must not
            # turn into a broken approval gate.
            logger.warning(
                "audit emission failed for action=%s (ignored)",
                action, exc_info=True,
            )


# -- ready-made approval callbacks -----------------------------------------


def cli_prompt_callback(action, cost, details=None,
                        input_fn=None, print_fn=print):
    # type: (str, Decimal, Optional[dict], Optional[Callable], Callable) -> bool
    """Interactive callback: show the request, read approval from stdin.

    Accepts "y"/"yes"/"s"/"si" (case-insensitive) as approval and
    "n"/"no" as denial; ANY other input denies — the safe default.
    ``input_fn``/``print_fn`` are injectable for tests; ``input_fn`` is
    resolved at call time so monkeypatching ``builtins.input`` also works.

    An EOF/interrupt on the prompt (closed or piped stdin, a headless
    run) also denies — the same safe default — instead of raising past
    ``ApprovalGate.require`` and skipping ``_record``'s audit entry for
    this decision (mirrors ``cli.py``'s own ``_read_answer``).
    """
    if input_fn is None:
        input_fn = input
    print_fn("Approval required for action: %s" % action)
    print_fn("Cost: %s" % cost)
    if details:
        print_fn("Details: %s" % details)
    try:
        answer = input_fn("Approve? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if answer in _APPROVE_ANSWERS:
        return True
    if answer in _DENY_ANSWERS:
        return False
    # Unrecognized input: deny.
    return False


def auto_deny_callback(action, cost, details=None):
    # type: (str, Decimal, Optional[dict]) -> bool
    """Deny everything in the gray zone (locked-down / unattended mode)."""
    return False


def always_approve_callback(action, cost, details=None):
    # type: (str, Decimal, Optional[dict]) -> bool
    """Approve everything in the gray zone. The hard ceiling STILL wins."""
    return True
