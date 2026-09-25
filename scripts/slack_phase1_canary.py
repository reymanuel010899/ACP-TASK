#!/usr/bin/env python
"""Phase 1 Slack canary: high-frequency bot read/message jobs.

Phase 1 asks for a high-frequency bot message/read canary "built only from
functionality the current flows already support", so that the provisional
shared contracts get exercised before generic schemas freeze. It is also the
traffic source for two other Phase 1 exit items: the product baselines, and
the sequential-chaining-versus-composition comparison that scopes U7.

The canary drives the real conversational service — the same
``coordinate_slack_turn`` / ``advance_slack_turn`` path the product uses — so
that interpretation, grounding, resolver pagination, approval, and dispatch
are all exercised. It deliberately does not call Slack directly; a canary that
bypasses the flow would measure the connector, not the product.

Usage::

    scripts/slack_phase1_canary.py --jobs 20 --channel tessera-test
    scripts/slack_phase1_canary.py --jobs 20 --compare      # chaining study
    scripts/slack_phase1_canary.py --baseline-only          # report, run nothing

Which halves run is read from the tenant control plane, not from the
environment: the canary must exercise exactly what the product would do for
this account, and an environment variable set only in the canary's own shell
would measure a configuration nobody is running. Read jobs need one of the
read families enabled; message jobs additionally need ``slack_messaging``.
When writes are off the canary still runs its read jobs and says plainly
which half it skipped, rather than reporting a partial run as a whole one.
"""

import argparse
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.orchestrator.brain import make_brain
from agents.orchestrator.conversation_state import ConciergeConversationStore
from agents.orchestrator.dynamic_workflow_service import DynamicWorkflowService
from agents.orchestrator.workflow_repository import WorkflowRepository
from libs.integrations.catalog import provider_definitions
from libs.integrations.control_plane import build_tenant_control_plane
from services.oauth.repository import OAuthRepository

TERMINAL_STATES = {"succeeded", "ready", "failed", "retryable_failure",
                   "unknown_outcome", "cancelled", "expired", "closed"}


READ_FAMILIES = (
    "slack_channel_discovery", "slack_conversation_reads",
    "slack_private_reads",
)


def build_service(workflows):
    connections = OAuthRepository(
        os.environ.get("OAUTH_DATABASE", "tessera-oauth.db")
    )
    control_plane = build_tenant_control_plane(
        connections, provider_definitions()
    )
    return DynamicWorkflowService(
        make_brain(),
        provider_definitions(),
        connections,
        workflows,
        rollout_version=os.environ.get(
            "TESSERA_CAPABILITY_ROLLOUT_VERSION", "production-v1"
        ),
        shadow_mode=False,
        conversation_store=ConciergeConversationStore(workflows),
        control_plane=control_plane,
    )


def settle(service, store, conversation_id, tenant_id, principal_id, approve,
           timeout):
    """Wait for the worker to drive a dispatched turn to a decidable state.

    A turn that reaches ``retrieving`` has handed off to a durable resolver
    workflow. Reporting that intermediate state as an outcome would make an
    unrun worker look like a product result, so the canary waits and says
    plainly when it timed out instead.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = store.get(conversation_id, tenant_id, principal_id,
                            include_terminal=True) or {}
        status = current.get("status")
        if status == "awaiting_approval" and approve:
            draft = current.get("pending_draft") or {}
            service.approve_slack_draft(
                conversation_id, tenant_id, principal_id, draft["draft_hash"],
            )
            service.complete_slack_write(
                conversation_id, tenant_id, principal_id
            )
            return "succeeded"
        if status in TERMINAL_STATES or status == "needs_input":
            return status
        if status == "awaiting_approval":
            return status
        time.sleep(0.5)
    return "timeout:%s" % (store.get(
        conversation_id, tenant_id, principal_id, include_terminal=True
    ) or {}).get("status", "unknown")


def run_job(service, store, tenant_id, principal_id, prompts, approve,
            timeout=30.0):
    """Drive one conversation to a decidable state, timing the whole turn."""
    started = time.time()
    conversation_id = None
    clarifications = 0
    state = None
    for prompt in prompts:
        payload = service.coordinate_slack_turn(
            tenant_id, principal_id, prompt, conversation_id=conversation_id,
        )
        conversation_id = payload["conversation_id"]
        result = service.advance_slack_turn(
            conversation_id, tenant_id, principal_id, prompt, payload,
        )
        state = result.get("state")
        if state == "needs_input":
            clarifications += 1
        if state in {"retrieving", "executing", "awaiting_approval"}:
            state = settle(service, store, conversation_id, tenant_id,
                           principal_id, approve, timeout)
            if state == "needs_input":
                clarifications += 1
    return {
        "conversation_id": conversation_id,
        "state": state,
        "clarifications": clarifications,
        "turns": len(prompts),
        "seconds": time.time() - started,
    }


def summarize(label, results):
    if not results:
        print("  %-26s (no jobs run)" % label)
        return
    reached = [r for r in results if r["state"] in {"succeeded", "ready"}]
    stalled = [r for r in results if str(r["state"]).startswith("timeout:")]
    times = [r["seconds"] for r in reached]
    if stalled:
        print("  %-26s AVISO: %d job(s) no alcanzaron un estado decidible; "
              "el worker puede no estar corriendo" % ("", len(stalled)))
    print("  %-26s jobs=%-4d completadas=%-4d clarificaciones/job=%.2f  mediana=%s"
          % (label, len(results), len(reached),
             statistics.mean([r["clarifications"] for r in results]),
             ("%.2fs" % statistics.median(times)) if times else "n/a"))
    states = {}
    for item in results:
        states[item["state"]] = states.get(item["state"], 0) + 1
    print("  %-26s estados: %s" % ("", ", ".join(
        "%s=%d" % (k, v) for k, v in sorted(states.items())
    )))


def report_baseline(workflows, tenant_id, since, until):
    rows = workflows.conversation_outcome_baseline(tenant_id, since, until)
    print("\n=== Baseline de resultados (concierge_outcome_events) ===")
    if not rows:
        print("  sin eventos en la ventana")
        return
    for row in sorted(rows, key=lambda r: (r["operation_family"] or "", r["event_type"])):
        print("  %-14s %-24s total=%-4d conversaciones=%d" % (
            row["operation_family"] or "-", row["event_type"],
            row["total"], row["conversations"],
        ))


def report_promotion_gates(workflows, tenant_id, since, until):
    """Per-family evidence, which is what a family enablement decision needs."""
    rows = workflows.family_promotion_report(tenant_id, since, until)
    print("\n=== Puertas de promocion por familia (R25) ===")
    if not rows:
        print("  sin evidencia en la ventana")
        return
    print("  %-16s %6s %6s %6s  %10s %10s  %s" % (
        "familia", "intent", "compl", "aband", "clarif/int", "prev->compl",
        "evidencia",
    ))
    for row in rows:
        def rate(value):
            return "n/a" if value is None else ("%.2f" % value)
        print("  %-16s %6d %6d %6d  %10s %10s  %s" % (
            row["family"], row["attempted"], row["completed"],
            row["abandoned"], rate(row["clarification_rate"]),
            rate(row["preview_conversion"]),
            "suficiente" if row["sufficient_evidence"] else "INSUFICIENTE",
        ))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=10)
    parser.add_argument("--channel", default="tessera-test")
    parser.add_argument("--tenant", default=os.environ.get(
        "TESSERA_LOCAL_TENANT_ID", "org:local"))
    parser.add_argument("--principal", default="canary:phase1")
    parser.add_argument("--compare", action="store_true",
                        help="also run the chaining-vs-composition comparison")
    parser.add_argument("--baseline-only", action="store_true",
                        help="report the existing baseline without running jobs")
    args = parser.parse_args(argv)

    workflows = WorkflowRepository(
        os.environ.get("WORKFLOW_DATABASE", "tessera-workflows.db")
    )
    since = int(time.time())

    if args.baseline_only:
        report_baseline(workflows, args.tenant, 0, since + 1)
        report_promotion_gates(workflows, args.tenant, 0, since + 1)
        return 0

    service = build_service(workflows)
    store = service.conversation_store
    families = service.control_plane.family_flags(args.tenant)
    stopped = service.control_plane.emergency_stop(args.tenant)
    writes = families.get("slack_messaging") is True
    reads = any(families.get(name) is True for name in READ_FAMILIES)

    print("=== Canary Phase 1 ===")
    print("  tenant=%s  canal=#%s  jobs=%d" % (args.tenant, args.channel, args.jobs))
    print("  lecturas=%s  escrituras=%s" % (reads, writes))
    if stopped:
        print("  AVISO: la cuenta esta detenida (parada de emergencia). No se")
        print("         despacha nada; no hay baseline que medir.")
    if not writes:
        print("  AVISO: la familia slack_messaging esta apagada — los jobs de")
        print("         mensaje se omiten. El embudo preview/aprobacion/completado")
        print("         no se mide, asi que el baseline resultante es parcial.")

    read_jobs, message_jobs, chained, composed = [], [], [], []
    for index in range(args.jobs):
        if reads:
            # Imperative phrasing on purpose. Interrogative reads
            # ("que se dijo en #x?") currently classify as unsupported, and a
            # canary measuring that would report a language gap as a product
            # failure rate. See docs/operations/slack-phase1-language-gate.md.
            read_jobs.append(run_job(
                service, store, args.tenant, args.principal,
                ["Lee los ultimos mensajes de #%s" % args.channel],
                approve=False,
            ))
        if writes:
            message_jobs.append(run_job(
                service, store, args.tenant, args.principal,
                ["Manda en #%s que canary %d" % (args.channel, index)],
                approve=True,
            ))
        if args.compare and writes:
            chained.append(run_job(
                service, store, args.tenant, args.principal,
                ["Quiero mandar un mensaje",
                 "En #%s" % args.channel,
                 "canary encadenado %d" % index],
                approve=True,
            ))
            composed.append(run_job(
                service, store, args.tenant, args.principal,
                ["Manda en #%s que canary compuesto %d" % (args.channel, index)],
                approve=True,
            ))

    print("\n=== Resultados ===")
    summarize("lectura", read_jobs)
    summarize("mensaje", message_jobs)
    if args.compare:
        print("\n=== Comparacion encadenado vs compuesto (escopa U7) ===")
        summarize("encadenado (3 turnos)", chained)
        summarize("compuesto (1 turno)", composed)
        if not (chained and composed):
            print("  comparacion no concluyente: requiere escrituras habilitadas")

    report_baseline(workflows, args.tenant, since, int(time.time()) + 1)
    report_promotion_gates(workflows, args.tenant, 0, int(time.time()) + 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
