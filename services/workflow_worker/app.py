"""Production worker for approved dynamic workflows."""

import argparse
import os
import socket
import time

from agents.orchestrator.action_repository import ActionRepository
from agents.orchestrator.broker_client import ActionBrokerClient
from agents.orchestrator.policy import PolicyEvaluator
from agents.orchestrator.workflow_broker_dispatcher import WorkflowBrokerDispatcher
from agents.orchestrator.workflow_executor import WorkflowExecutor
from agents.orchestrator.workflow_repository import WorkflowRepository
from services.oauth.repository import OAuthRepository
from libs.integrations.catalog import google_definitions, slack_definitions


def _enabled():
    return os.environ.get("TESSERA_DYNAMIC_EXECUTION_ENABLED", "false").lower() == "true"


class WorkflowWorker:
    OUTBOX_VISIBILITY_SECONDS = 30
    OUTBOX_RETRY_SECONDS = 5

    def __init__(self, workflows, executor, worker_id=None):
        self.workflows = workflows
        self.executor = executor
        self.worker_id = worker_id or "workflow-worker:%s:%s" % (socket.gethostname(), os.getpid())

    def run_once(self):
        outcomes = []
        now = int(time.time())
        if hasattr(self.workflows, "recover_expired_claims"):
            self.workflows.recover_expired_claims(now)
        if hasattr(self.workflows, "purge_expired_content"):
            self.workflows.purge_expired_content(now)
        if hasattr(self.workflows, "recover_unprojected_conversation_outcomes"):
            self.workflows.recover_unprojected_conversation_outcomes(now)
        if _enabled() and hasattr(self.workflows, "resume_policy_paused"):
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
        return outcomes

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
                self.workflows.fail_outbox_event(
                    event["event_id"], event["tenant_id"], self.worker_id,
                    now, type(exc).__name__, self.OUTBOX_RETRY_SECONDS,
                )
        return drained

    def _project_event(self, event, now):
        event_type = event.get("event_type")
        if event_type not in {
            "workflow.outcome",
            "conversation.turn_committed",
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
    actions = ActionRepository(os.environ.get("ACTION_DATABASE", "tessera-actions.db"))
    connections = OAuthRepository(os.environ.get("OAUTH_DATABASE", "tessera-oauth.db"))
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
        policy_evaluator=PolicyEvaluator(
            google_definitions() + slack_definitions(), rollout_version
        ),
    )
    executor = WorkflowExecutor(workflows, dispatcher, policy=lambda _step: _enabled())
    return WorkflowWorker(workflows, executor)


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
