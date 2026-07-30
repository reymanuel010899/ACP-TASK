"""Production worker for approved dynamic workflows."""

import argparse
import os
import socket
import time

from agents.orchestrator.action_repository import ActionRepository
from agents.orchestrator.broker_client import ActionBrokerClient
from agents.orchestrator.workflow_broker_dispatcher import WorkflowBrokerDispatcher
from agents.orchestrator.workflow_executor import WorkflowExecutor
from agents.orchestrator.workflow_repository import WorkflowRepository
from services.oauth.repository import OAuthRepository


def _enabled():
    return os.environ.get("TESSERA_DYNAMIC_EXECUTION_ENABLED", "false").lower() == "true"


class WorkflowWorker:
    def __init__(self, workflows, executor, worker_id=None):
        self.workflows = workflows
        self.executor = executor
        self.worker_id = worker_id or "workflow-worker:%s:%s" % (socket.gethostname(), os.getpid())

    def run_once(self):
        outcomes = []
        if hasattr(self.workflows, "recover_expired_claims"):
            self.workflows.recover_expired_claims(int(time.time()))
        if hasattr(self.workflows, "purge_expired_content"):
            self.workflows.purge_expired_content(int(time.time()))
        if _enabled() and hasattr(self.workflows, "resume_policy_paused"):
            self.workflows.resume_policy_paused()
        for revision in self.workflows.list_approved_revisions():
            try:
                outcomes.append(self.executor.run_until_blocked(
                    revision["workflow_run_id"], revision["workflow_revision_id"],
                    revision["tenant_id"], self.worker_id,
                ))
            except Exception as exc:
                outcomes.append({
                    "status": "worker_error",
                    "workflow_revision_id": revision["workflow_revision_id"],
                    "error": type(exc).__name__,
                })
        return outcomes


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
    dispatcher = WorkflowBrokerDispatcher(
        actions, broker, connections, workflows,
        rollout_version=os.environ.get(
            "TESSERA_CAPABILITY_ROLLOUT_VERSION", "production-v1"
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
