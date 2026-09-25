"""Production worker for approved dynamic workflows."""

import argparse
import os
import socket
import time

from agents.orchestrator.action_repository import (
    ActionRepository,
    PostgresActionRepository,
)
from agents.orchestrator.brain import make_brain
from agents.orchestrator.broker_client import ActionBrokerClient
from agents.orchestrator.conversation_state import ConciergeConversationStore
from agents.orchestrator.dynamic_workflow_service import DynamicWorkflowService
from agents.orchestrator.policy import PolicyEvaluator
from agents.orchestrator.reconciliation import WorkflowReconciler
from agents.orchestrator.workflow_broker_dispatcher import WorkflowBrokerDispatcher
from agents.orchestrator.workflow_executor import WorkflowExecutor
from agents.orchestrator.workflow_repository import (
    PostgresWorkflowRepository,
    WorkflowRepository,
)
from services.oauth.repository import (
    OAuthRepository,
    PkceCipher,
    PostgresOAuthRepository,
)
from libs.integrations.catalog import provider_definitions
from libs.integrations.control_plane import build_tenant_control_plane


class WorkflowWorker:
    OUTBOX_VISIBILITY_SECONDS = 30
    OUTBOX_RETRY_SECONDS = 5

    def __init__(self, workflows, executor, worker_id=None,
                 conversation_resolver=None, reconciler=None, actions=None):
        self.workflows = workflows
        self.executor = executor
        self.conversation_resolver = conversation_resolver
        self.reconciler = reconciler
        self.actions = actions
        self.worker_id = worker_id or "workflow-worker:%s:%s" % (socket.gethostname(), os.getpid())

    def run_once(self):
        outcomes = []
        now = int(time.time())
        if hasattr(self.workflows, "recover_expired_claims"):
            self.workflows.recover_expired_claims(now)
        self._sweep_stalled_dispatches(now)
        self._reconcile_unknown_effects(now)
        if hasattr(self.workflows, "purge_expired_content"):
            self.workflows.purge_expired_content(now)
        if hasattr(self.workflows, "recover_unprojected_conversation_outcomes"):
            self.workflows.recover_unprojected_conversation_outcomes(now)
        # Unconditional now that the switches are per-tenant. Gating the
        # resume on a process-wide flag meant work parked by a control-plane
        # change stayed parked until someone restarted this process, which is
        # precisely the property this unit removes. The repository still
        # decides which pauses are resumable; a stop lifted at 09:00 drains on
        # the next tick, and a pause that needs a replan stays put.
        if hasattr(self.workflows, "resume_policy_paused"):
            self.workflows.resume_policy_paused()
        list_revisions = getattr(
            self.workflows, "list_runnable_revisions",
            self.workflows.list_approved_revisions if hasattr(
                self.workflows, "list_approved_revisions"
            ) else None,
        )
        for revision in list_revisions():
            try:
                outcome = self.executor.run_until_blocked(
                    revision["workflow_run_id"], revision["workflow_revision_id"],
                    revision["tenant_id"], self.worker_id,
                )
                outcomes.append(outcome)
                if hasattr(self.workflows, "enqueue_workflow_conversation_outcome"):
                    self.workflows.enqueue_workflow_conversation_outcome(
                        revision["workflow_revision_id"], revision["tenant_id"],
                        outcome, now,
                    )
            except Exception as exc:
                outcomes.append({
                    "status": "worker_error",
                    "workflow_revision_id": revision["workflow_revision_id"],
                    "error": type(exc).__name__,
                })
        self._drain_outbox(now)
        self._resume_slack_resolver_runs(now)
        self._resume_slack_reads(now)
        return outcomes

    def _sweep_stalled_dispatches(self, now):
        """Free claims whose lease died mid-flight.

        A proposal left in `executing` has no path to any verdict on its own,
        and it blocks every later attempt on that step forever.
        """
        if self.actions is None or not hasattr(
            self.actions, "sweep_stalled_executions"
        ):
            return None
        try:
            return self.actions.sweep_stalled_executions(now)
        except Exception:
            return None

    def _reconcile_unknown_effects(self, now):
        """Ask the provider what happened, so unknown is never the last word."""
        if self.reconciler is None:
            return []
        try:
            return self.reconciler.run_once(now)
        except Exception:
            return []

    def _resume_slack_reads(self, now):
        """Fetch the next page of a read still inside its budget."""
        resolver = self.conversation_resolver
        if resolver is None or not hasattr(
            self.workflows, "list_paging_slack_reads"
        ):
            return 0
        resumed = 0
        for conversation in self.workflows.list_paging_slack_reads(now):
            try:
                if resolver.continue_slack_read(conversation, now):
                    resumed += 1
            except Exception:
                continue
        return resumed

    def _resume_slack_resolver_runs(self, now):
        """Page durable resolver runs forward after completion or restart."""
        resolver = self.conversation_resolver
        if resolver is None or not hasattr(
            self.workflows, "list_resumable_slack_resolver_runs"
        ):
            return 0
        resumed = 0
        for run in self.workflows.list_resumable_slack_resolver_runs(now):
            try:
                if resolver.continue_slack_resolver_run(run, now):
                    resumed += 1
            except Exception:
                continue
        return resumed

    def _drain_outbox(self, now, limit=100):
        if not hasattr(self.workflows, "claim_outbox_event"):
            return 0
        drained = 0
        for _index in range(int(limit)):
            event = self.workflows.claim_outbox_event(
                self.worker_id, now, self.OUTBOX_VISIBILITY_SECONDS
            )
            if event is None:
                break
            try:
                self._project_event(event, now)
                self.workflows.complete_outbox_event(
                    event["event_id"], event["tenant_id"], self.worker_id, now
                )
                drained += 1
            except Exception as exc:
                disposition = self.workflows.fail_outbox_event(
                    event["event_id"], event["tenant_id"], self.worker_id,
                    now, type(exc).__name__, self.OUTBOX_RETRY_SECONDS,
                )
                if disposition == "dead_letter":
                    self._strand_conversation(event, now, type(exc).__name__)
        return drained

    def _strand_conversation(self, event, now, error_code):
        """Give up loudly: a dead event must not leave a turn polling forever."""
        if event.get("aggregate_type") != "conversation":
            return False
        principal_id = (event.get("payload") or {}).get("principal_id")
        if not principal_id or not hasattr(
            self.workflows, "update_conversation"
        ):
            return False
        try:
            return bool(self.workflows.update_conversation(
                event["aggregate_id"], event["tenant_id"], principal_id,
                {
                    "status": "retryable_failure",
                    "blocking_need": {
                        "kind": "recovery", "field": "operation", "options": [],
                        "question": "No pude completar esa consulta. "
                                    "¿Quieres intentarlo de nuevo?",
                        "error_code": error_code,
                    },
                },
                now,
            ))
        except Exception:
            return False

    def _apply_resolver_completion(self, event, now):
        """Continue the conversation server-side so polling stays read-only."""
        resolver = self.conversation_resolver
        if resolver is None:
            return False
        return bool(resolver.apply_slack_resolver_completion(
            event["tenant_id"], event["aggregate_id"],
            event.get("payload") or {}, now,
        ))

    def _project_event(self, event, now):
        event_type = event.get("event_type")
        if event_type not in {
            "workflow.outcome",
            "conversation.turn_committed",
            "conversation.resolver_completed",
        }:
            raise ValueError("unsupported outbox event type")
        watermark = self.workflows.get_projection_watermark(
            event["tenant_id"], event["aggregate_type"], event["aggregate_id"]
        ) if hasattr(self.workflows, "get_projection_watermark") else None
        if watermark and int(watermark["projected_version"]) >= int(
            event["aggregate_version"]
        ):
            return False
        if event_type == "workflow.outcome":
            payload = event.get("payload") or {}
            projected = self.workflows.sync_conversation_workflow_outcome(
                payload["revision_id"], event["tenant_id"], payload["outcome"], now
            )
            if not projected:
                raise RuntimeError("conversation outcome was not projectable")
        if event_type == "conversation.resolver_completed":
            self._apply_resolver_completion(event, now)
        advanced = self.workflows.advance_projection_watermark(
            event["tenant_id"], event["aggregate_type"], event["aggregate_id"],
            event["aggregate_version"], event["event_id"], now,
        )
        if not advanced:
            current = self.workflows.get_projection_watermark(
                event["tenant_id"], event["aggregate_type"], event["aggregate_id"]
            )
            if not current or int(current["projected_version"]) < int(
                event["aggregate_version"]
            ):
                raise RuntimeError("projection watermark did not advance")
        return True


def build_worker():
    workflows = WorkflowRepository.from_environment(
        os.environ.get("WORKFLOW_DATABASE", "tessera-workflows.db"),
        os.environ.get("TESSERA_WORKFLOW_WORKER_IDENTITY", "service:workflow-worker"),
    )
    if isinstance(workflows, PostgresWorkflowRepository):
        actions = PostgresActionRepository(workflows.db)
        pkce_key = os.environ.get("OAUTH_TRANSACTION_ENCRYPTION_KEY")
        if not pkce_key:
            raise RuntimeError("OAUTH_TRANSACTION_ENCRYPTION_KEY is required")
        connections = PostgresOAuthRepository(
            workflows.db, PkceCipher(pkce_key)
        )
    else:
        actions = ActionRepository(
            os.environ.get("ACTION_DATABASE", "tessera-actions.db")
        )
        connections = OAuthRepository(
            os.environ.get("OAUTH_DATABASE", "tessera-oauth.db")
        )
    broker = ActionBrokerClient(
        os.environ["TESSERA_ACTION_BROKER_URL"],
        os.environ["TESSERA_ACTION_BROKER_INTERNAL_TOKEN"],
    )
    rollout_version = os.environ.get(
        "TESSERA_CAPABILITY_ROLLOUT_VERSION", "production-v1"
    )
    dispatcher = WorkflowBrokerDispatcher(
        actions, broker, connections, workflows,
        rollout_version=rollout_version,
        # Which agent this worker acts as. The broker refuses a side-effecting
        # dispatch whose agent has no trusted endpoint and cannot re-prove its
        # identity, so a worker hardcoded to a principal the deployment never
        # publishes can read but can never write. Deployments name the agent
        # they actually run; the default keeps existing ones unchanged.
        agent_principal_id=os.environ.get(
            "TESSERA_WORKFLOW_AGENT_PRINCIPAL_ID", "agent:orchestrator"
        ),
        policy_evaluator=PolicyEvaluator(
            provider_definitions(), rollout_version
        ),
    )
    # One control plane, shared by the executor and the conversation
    # resolver: two readers of two different sources is how a stop ends up
    # half-applied.
    control_plane = build_tenant_control_plane(
        connections, provider_definitions()
    )
    # The step policy is now a per-tenant decision that carries its own
    # reason, so a step parked by an emergency stop is distinguishable from
    # one parked by a family disable, and both resume on the next tick after
    # the administrator reverses them.
    executor = WorkflowExecutor(
        workflows, dispatcher, policy=control_plane.decide_step
    )
    return WorkflowWorker(
        workflows, executor,
        conversation_resolver=_build_conversation_resolver(
            workflows, connections, rollout_version, control_plane
        ),
        reconciler=WorkflowReconciler(
            workflows, actions, reconcilers=_provider_reconcilers()
        ),
        actions=actions,
    )


def _provider_reconcilers():
    """Provider-side reconcilers, keyed by capability family.

    Registering nothing is a deliberate, visible state: an unknown effect is
    still swept, bounded, and escalated for a human, rather than silently
    stranded. A family becomes self-healing the moment it registers here.
    """
    return {}


def _build_conversation_resolver(
    workflows, connections, rollout_version, control_plane,
):
    """Own resolver continuation here so HTTP polling stays read-only."""
    return DynamicWorkflowService(
        make_brain(),
        provider_definitions(),
        connections,
        workflows,
        rollout_version=rollout_version,
        shadow_mode=os.environ.get(
            "TESSERA_DYNAMIC_PLANNER_SHADOW", "true"
        ).lower() != "false",
        conversation_store=ConciergeConversationStore(workflows),
        # Which families this account holds is durable per-tenant state now,
        # not three environment variables read once at boot.
        control_plane=control_plane,
    )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args(argv)
    worker = build_worker()
    while True:
        worker.run_once()
        time.sleep(max(0.1, args.poll_seconds))


if __name__ == "__main__":
    main()
