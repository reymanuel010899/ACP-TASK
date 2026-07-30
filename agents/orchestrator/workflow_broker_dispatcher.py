"""Convert an approved workflow step into one exact broker dispatch."""

import time

from agents.orchestrator.action_repository import canonical_payload_hash
from agents.orchestrator.workflow_executor import (
    AmbiguousStepError, CorrectableStepError, RetryableStepError,
)


def _matches_approved_template(template, resolved):
    """Allow only substitutions explicitly declared by a $ref in the approved graph."""
    if isinstance(template, dict) and set(template) == {"$ref"}:
        return True
    if isinstance(template, dict):
        return (
            isinstance(resolved, dict)
            and set(template) == set(resolved)
            and all(_matches_approved_template(template[key], resolved[key]) for key in template)
        )
    if isinstance(template, list):
        return (
            isinstance(resolved, list)
            and len(template) == len(resolved)
            and all(_matches_approved_template(left, right) for left, right in zip(template, resolved))
        )
    return template == resolved


class WorkflowBrokerDispatcher:
    def __init__(self, actions, broker, connections, workflows,
                 agent_principal_id="agent:orchestrator", clock=None, ttl=300,
                 rollout_version="production-v1"):
        self.actions = actions
        self.broker = broker
        self.connections = connections
        self.workflows = workflows
        self.agent_principal_id = agent_principal_id
        self.clock = clock or time.time
        self.ttl = int(ttl)
        self.rollout_version = rollout_version

    def __call__(self, step, claim):
        run = self.workflows.get_run(step["workflow_run_id"], step["tenant_id"])
        revision = self.workflows.get_revision(
            step["workflow_run_id"], claim["workflow_revision_id"], step["tenant_id"]
        )
        connection = self.connections.get_installation(
            step["connection_id"], step["tenant_id"]
        )
        if not connection or connection.get("status") != "connected":
            raise RetryableStepError("connection is unavailable")
        approved_credential_version = int(step.get("credential_version") or 0)
        if approved_credential_version and int(
            connection.get("credential_version") or 0
        ) != approved_credential_version:
            raise PermissionError("credential version changed; replan required")
        if (
            "enabled_capabilities" in connection
            and step["capability_id"] not in set(connection.get("enabled_capabilities") or ())
        ):
            raise CorrectableStepError("missing_scope:reconnect_installation")
        now = int(self.clock())
        authorized = self.workflows.is_step_authorized(
            step["workflow_run_id"], claim["workflow_revision_id"],
            step["tenant_id"], revision["plan_graph_hash"], step["effect"], now,
        ) if hasattr(self.workflows, "is_step_authorized") else self.workflows.is_revision_approved(
            step["workflow_run_id"], claim["workflow_revision_id"],
            step["tenant_id"], revision["plan_graph_hash"], now,
        )
        if not authorized:
            raise PermissionError("workflow approval expired before dispatch")
        if not _matches_approved_template(step.get("approved_input", step["input"]), step["input"]):
            raise PermissionError("resolved effect no longer matches the approved graph")
        task_id = "%s:%s" % (claim["workflow_revision_id"], step["step_id"])
        binding = {
            "user_principal_id": run["user_principal_id"],
            "agent_principal_id": self.agent_principal_id,
            "task_id": task_id,
            "credential_id": connection["credential_id"],
            "capability_id": step["capability_id"],
            "connection_id": step["connection_id"],
            "tenant_id": step["tenant_id"],
            "workflow_revision_id": claim["workflow_revision_id"],
            "step_id": step["step_id"],
            "plan_graph_hash": revision["plan_graph_hash"],
            "attempt": claim["attempt"],
            "team_id": connection.get("team_id"),
            "bot_user_id": connection.get("bot_user_id"),
            "connection_snapshot": {
                "connection_id": step["connection_id"], "tenant_id": step["tenant_id"],
                "capability_id": step["capability_id"], "capability_version": step["capability_version"],
                "credential_version": connection["credential_version"],
                "effective_scopes": connection.get("granted_scopes", []),
                "health": "healthy", "rollout_version": self.rollout_version,
            },
        }
        if step["effect"] == "write":
            proposal = self.actions.create_proposal(
                run["user_principal_id"], self.agent_principal_id,
                connection["credential_id"], step["capability_id"], step["input"],
                now + self.ttl,
                proposal_id="proposal:%s" % task_id,
                idempotency_key="workflow:%s:%s" % (claim["workflow_revision_id"], step["step_id"]),
                workflow_revision_id=claim["workflow_revision_id"], step_id=step["step_id"],
                plan_graph_hash=revision["plan_graph_hash"], connection_id=step["connection_id"],
                attempt=claim["attempt"],
            )
            if not self.actions.decide(
                proposal["proposal_id"], proposal["version"],
                run["user_principal_id"], True, now,
            ):
                raise PermissionError("exact action approval could not be materialized")
            binding.update({
                "proposal_id": proposal["proposal_id"], "version": proposal["version"],
                "payload_hash": canonical_payload_hash(step["input"]),
                "idempotency_key": proposal["idempotency_key"],
            })
        lease = self.actions.issue_lease(
            run["user_principal_id"], self.agent_principal_id, task_id,
            connection["credential_id"], [step["capability_id"]], now + self.ttl,
            workflow_revision_id=claim["workflow_revision_id"],
            step_id=step["step_id"], plan_graph_hash=revision["plan_graph_hash"],
            connection_id=step["connection_id"], attempt=claim["attempt"],
        )
        status, body = self.broker.execute(lease, binding, step["input"])
        if status == 202:
            raise AmbiguousStepError("provider outcome requires reconciliation")
        if status >= 500 and step["effect"] == "write":
            raise AmbiguousStepError("provider write outcome requires reconciliation")
        if status >= 500:
            raise RetryableStepError(
                "provider is temporarily unavailable", body.get("retry_after")
            )
        if status == 429:
            raise RetryableStepError(
                "provider is rate limited", body.get("retry_after")
            )
        if status != 200:
            raise PermissionError(body.get("error") or "broker rejected the live authorization")
        return {
            "receipt": body.get("receipt", {}),
            "output": body.get("receipt", {}),
            "attestation": body.get("execution_attestation"),
        }
