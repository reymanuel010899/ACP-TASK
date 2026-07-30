"""CLI entry point + interactive conversation for the orchestrator (U25).

Thin glue only (R8): argument parsing, a clarification/REPL loop and
rendering. All behavior lives in the committed units it wires together:

* brain     -> :func:`agents.orchestrator.brain.make_brain` (U21) —
  ClaudeBrain with an ANTHROPIC_API_KEY, offline RuleBrain otherwise
  (a one-line notice says so);
* gate      -> :class:`agents.orchestrator.approval.ApprovalGate` (U23)
  over a :class:`SpendPolicy` built from ``--auto-approve-under`` /
  ``--hard-ceiling``, with the interactive
  :func:`~agents.orchestrator.approval.cli_prompt_callback`;
* tools     -> :class:`agents.orchestrator.tools.OrchestratorTools` (U22)
  over the ``--registry-url`` / ``--agent-marketplace-url`` /
  ``--vault-url`` rails;
* agent     -> :class:`agents.orchestrator.agent.OrchestratorAgent` (U24).

Run (one-shot):

    python -m agents.orchestrator.cli --registry-url http://localhost:8090 \
        --request "necesito enviar un paquete a Santiago"

Without ``--request`` the CLI runs an interactive REPL (Ctrl-D / "salir"
to quit). ``needs_clarification`` outcomes print the concierge's question
and re-invoke the agent with the combined request once the user answers;
in one-shot mode with no answer available the question is printed and the
CLI exits 0. Registry-unreachable degrades to a warning; only bad
arguments exit non-zero.

``main`` is designed for injection: ``agent_factory(args)`` replaces the
default :func:`build_agent`, and ``input_fn`` replaces ``input`` for
scripted stdin in tests.
"""

import argparse
import sys
from decimal import Decimal, InvalidOperation

from agents.orchestrator.agent import DEFAULT_AGENT_ID, OrchestratorAgent
from agents.orchestrator.approval import (
    ApprovalGate,
    SpendPolicy,
    cli_prompt_callback,
)
from agents.orchestrator.brain import RuleBrain, make_brain
from agents.orchestrator.tools import OrchestratorTools

#: Commands that leave the interactive REPL.
_QUIT_WORDS = frozenset(("exit", "quit", "salir"))


def _decimal_arg(value):
    # type: (str) -> Decimal
    """argparse type: a Decimal amount, with a clear error otherwise."""
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        raise argparse.ArgumentTypeError(
            "%r is not a valid decimal amount" % (value,)
        )


def build_parser():
    # type: () -> argparse.ArgumentParser
    parser = argparse.ArgumentParser(
        prog="python -m agents.orchestrator.cli",
        description="Orchestrator concierge over the agent ecosystem "
        "(U25). One-shot with --request, interactive REPL without it.",
    )
    parser.add_argument(
        "--registry-url", required=True,
        help="Registry base URL (registration, discovery, P2P rails).",
    )
    parser.add_argument(
        "--vault-url", default=None,
        help="Vault base URL (credential access; optional).",
    )
    parser.add_argument(
        "--agent-marketplace-url", default=None,
        help="Agent-marketplace base URL (agent discovery; optional).",
    )
    parser.add_argument(
        "--agent-id", default=DEFAULT_AGENT_ID,
        help="Agent principal_id (default: %s)." % DEFAULT_AGENT_ID,
    )
    parser.add_argument(
        "--request", default=None,
        help="One-shot natural-language request; omit for a REPL.",
    )
    parser.add_argument(
        "--auto-approve-under", type=_decimal_arg, default=Decimal("0"),
        help="Spends strictly below this are approved without asking "
        "(default: 0 — every spend asks).",
    )
    parser.add_argument(
        "--hard-ceiling", type=_decimal_arg, default=Decimal("20"),
        help="Spends strictly above this are refused outright "
        "(default: 20).",
    )
    parser.add_argument(
        "--require-signatures", action="store_true",
        help="Secure mode: generate a fresh keypair and sign every "
        "P2P/vault request with a SessionContext.",
    )
    parser.add_argument(
        "--credential-id", default=None,
        help="Vault credential the work needs (optional; access is "
        "gated by the approval policy).",
    )
    return parser


def build_agent(args):
    # type: (argparse.Namespace) -> OrchestratorAgent
    """Wire brain + gate + tools + agent from parsed args (default
    ``agent_factory``). Raises ValueError/TypeError on bad limits."""
    brain = make_brain()
    if isinstance(brain, RuleBrain):
        print(
            "No ANTHROPIC_API_KEY configured; falling back to the "
            "offline RuleBrain."
        )

    policy = SpendPolicy(
        auto_approve_under=args.auto_approve_under,
        hard_ceiling=args.hard_ceiling,
    )

    session = None
    # The session's principal_id MUST equal the identity every rail signs
    # requests as (libs/agent_coordination.py), or the apps 403 every
    # signed call as an identity mismatch. Under the MVP convention the
    # session principal_id IS the base64 public key, so that key becomes
    # the effective agent identity everywhere once secure mode is on
    # (mirrors the U26 E2E secure-mode fixture).
    effective_agent_id = args.agent_id
    if args.require_signatures:
        from libs import signing
        from libs.session import SessionContext

        principal = signing.generate_keypair()
        effective_agent_id = principal.public_key_b64()
        session = SessionContext.create(
            effective_agent_id, principal.signing_key
        )

    gate = ApprovalGate(
        policy, cli_prompt_callback, principal_id=effective_agent_id
    )
    tools = OrchestratorTools(
        registry_url=args.registry_url,
        agent_marketplace_url=args.agent_marketplace_url,
        vault_url=args.vault_url,
        gate=gate,
        agent_principal_id=effective_agent_id,
        session=session,
    )
    return OrchestratorAgent(
        registry_url=args.registry_url,
        brain=brain,
        tools=tools,
        gate=gate,
        session=session,
        agent_id=effective_agent_id,
        credential_id=args.credential_id,
    )


def _read_answer(input_fn, prompt="> "):
    # type: (object, str) -> object
    """One line of user input, stripped; ``None`` only on real EOF/
    interrupt. An empty line returns ``""`` (distinct from EOF) so
    callers can re-prompt instead of treating Enter as "quit"."""
    try:
        answer = input_fn(prompt)
    except (EOFError, KeyboardInterrupt):
        return None
    return (answer or "").strip()


def run_request(agent, request, input_fn):
    # type: (OrchestratorAgent, str, object) -> object
    """Drive ONE request to its final outcome, looping on clarification.

    Prints every reply. On ``needs_clarification`` the question is
    printed and the user's answer is appended to the request for the
    re-invocation; with no answer available (one-shot, stdin exhausted)
    the question stands as the outcome. Returns the final Result.
    """
    while True:
        result = agent.handle_request(request)
        print(result.reply)
        if result.status != "needs_clarification":
            return result
        answer = _read_answer(input_fn)
        if answer is None:
            return result
        if not answer:
            continue
        request = "%s %s" % (request, answer)


def _repl(agent, input_fn):
    # type: (OrchestratorAgent, object) -> int
    print(
        "Orchestrator concierge. Escriba su solicitud "
        "(Ctrl-D o 'salir' para terminar)."
    )
    while True:
        line = _read_answer(input_fn, "orchestrator> ")
        if line is None:
            print("Hasta luego.")
            return 0
        if not line:
            continue
        if line.lower() in _QUIT_WORDS:
            print("Hasta luego.")
            return 0
        run_request(agent, line, input_fn)


def main(argv=None, agent_factory=None, input_fn=None):
    # type: (object, object, object) -> int
    parser = build_parser()
    args = parser.parse_args(argv)
    if input_fn is None:
        input_fn = input
    if agent_factory is None:
        agent_factory = build_agent

    try:
        agent = agent_factory(args)
    except (ValueError, TypeError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    if not agent.register():
        print(
            "warning: could not register with the registry at %s; "
            "continuing anyway." % args.registry_url
        )

    if args.request is not None:
        run_request(agent, args.request, input_fn)
        return 0
    return _repl(agent, input_fn)


if __name__ == "__main__":
    raise SystemExit(main())
