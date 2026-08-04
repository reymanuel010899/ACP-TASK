"""Convert an approved workflow step into one exact broker dispatch."""

import time

from agents.orchestrator.action_repository import canonical_payload_hash
from libs.integrations.catalog import capability_retry_policy
from agents.orchestrator.workflow_executor import (
    AmbiguousStepError, CorrectableStepError, PausedStepError,
    RetryableStepError,
)


def _pre_dispatch_rejection(exc):
    """Classify a failure raised before the broker call.

    Nothing has reached the provider yet, so this outcome is known: no effect
    occurred. Letting it fall through to the executor's bare exception handler
    would record it as `execution_unknown` and manufacture uncertainty about
    an effect that provably never left this process.
    """
    if isinstance(exc, (
        PermissionError, CorrectableStepError, RetryableStepError,
        PausedStepError, AmbiguousStepError,
    )):
        return exc
    return CorrectableStepError("pre_dispatch:%s" % type(exc).__name__)


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


def _raise_for_broker_failure(status, body, effect, retry_policy="reconcile"):
    # An idempotent write converges on the same state however many times it
    # runs, so an unknown outcome is a retry rather than a reconciliation.
    # Treating every write as ambiguous strands operations that were never at
    # risk of duplicating anything.
    repeatable = effect != "write" or retry_policy == "idempotent"
    if status == 202:
        if repeatable:
            raise RetryableStepError(
                "provider outcome is unknown but the effect is repeatable"
            )
        raise AmbiguousStepError("provider outcome requires reconciliation")
    if status >= 500:
        if not repeatable and body.get("outcome_certainty") != "safe":
            raise AmbiguousStepError(
                "provider write outcome requires reconciliation"
            )
        raise RetryableStepError(
            "provider is temporarily unavailable", body.get("retry_after")
        )
    if status == 429:
        raise RetryableStepError(
            "provider is rate limited", body.get("retry_after")
        )
    category = body.get("category")
    if category in {"scope", "membership", "permission", "validation", "provider"}:
        raise CorrectableStepError(
            "%s:%s" % (category, body.get("error") or "provider_rejected")
        )
    if status == 422:
        raise CorrectableStepError(
            body.get("error") or "broker rejected the request schema"
        )
    raise PermissionError(
        body.get("error") or "broker rejected the live authorization"
    )


class WorkflowBrokerDispatcher:
    def __init__(self, actions, broker, connections, workflows,
                 agent_principal_id="agent:orchestrator", clock=None, ttl=300,
                 rollout_version="production-v1", policy_evaluator=None):
        self.actions = actions
        self.broker = broker
        self.connections = connections
        self.workflows = workflows
        self.agent_principal_id = agent_principal_id
        self.clock = clock or time.time
        self.ttl = int(ttl)
        self.rollout_version = rollout_version
        self.policy_evaluator = policy_evaluator

    def __call__(self, step, claim):
        run = self.workflows.get_run(step["workflow_run_id"], step["tenant_id"])
        revision = self.workflows.get_revision(
            step["workflow_run_id"], claim["workflow_revision_id"], step["tenant_id"]
        )
        connection = self.connections.get_installation(
            step["connection_id"], step["tenant_id"]
        )
        if not connection or connection.get("status") != "connected":
            # A provider outage is not the step's fault, so it waits rather
            # than spending an attempt it can never win back.
            raise PausedStepError("connection is unavailable")
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
        approval_expires_at = now + self.ttl if step["effect"] == "write" else None
        approval_payload_hash = (
            canonical_payload_hash(step["input"])
            if step["effect"] == "write" else None
        )
        binding = {
            "user_principal_id": run["user_principal_id"],
            "agent_principal_id": self.agent_principal_id,
            "task_id": task_id,
            "credential_id": connection["credential_id"],
            "capability_id": step["capability_id"],
            "connection_id": step["connection_id"],
            "tenant_id": step["tenant_id"],
            "authority_profile": connection.get("authority_profile", "bot"),
            # Whose token this acts as travels with the dispatch, so the
            # approval, the lease, and the receipt all name the same subject.
            "authority_profile_id": connection.get("authority_profile_id"),
            "slack_subject_id": connection.get("slack_subject_id"),
            "authority_authorization": connection.get("authority_authorization"),
            "credential_version": connection["credential_version"],
            "capability_version": step["capability_version"],
            "descriptor_snapshot_hash": step["descriptor_snapshot_hash"],
            "effect": step["effect"],
            "workflow_revision_id": claim["workflow_revision_id"],
            "step_id": step["step_id"],
            "plan_graph_hash": revision["plan_graph_hash"],
            "attempt": claim["attempt"],
            "approval_payload_hash": approval_payload_hash,
            "approval_expires_at": approval_expires_at,
            "payload_hash": approval_payload_hash,
            "slack_connect": step.get("slack_connect", False),
            "data_egress": step.get("data_egress", False),
            "team_id": connection.get("team_id"),
            "bot_user_id": connection.get("bot_user_id"),
            "connection_snapshot": {
                "connection_id": step["connection_id"], "tenant_id": step["tenant_id"],
                "capability_id": step["capability_id"], "capability_version": step["capability_version"],
                "credential_version": connection["credential_version"],
                "effective_scopes": connection.get("granted_scopes", []),
                "health": "healthy", "rollout_version": self.rollout_version,
                "authority_profile": connection.get("authority_profile", "bot"),
            },
        }
        if self.policy_evaluator is not None:
            decision = self.policy_evaluator.evaluate(binding, connection, now)
            if not decision["allowed"]:
                raise PermissionError(
                    "dynamic policy denied: %s" % decision["reason"]
                )
            binding["policy_decision"] = decision
        if step["effect"] == "write":
            # Materializing the exact action can refuse — most importantly when
            # a prior attempt is still unresolved — and every such refusal
            # happens before dispatch, so it must be classified here rather
            # than escaping as an unknown provider outcome.
            try:
                proposal = self.actions.create_proposal(
                    run["user_principal_id"], self.agent_principal_id,
                    connection["credential_id"], step["capability_id"], step["input"],
                    approval_expires_at,
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
            except Exception as exc:
                raise _pre_dispatch_rejection(exc)
            binding.update({
                "proposal_id": proposal["proposal_id"], "version": proposal["version"],
                "payload_hash": canonical_payload_hash(step["input"]),
                "idempotency_key": proposal["idempotency_key"],
            })
        try:
            lease = self.actions.issue_lease(
                run["user_principal_id"], self.agent_principal_id, task_id,
                connection["credential_id"], [step["capability_id"]], now + self.ttl,
                workflow_revision_id=claim["workflow_revision_id"],
                step_id=step["step_id"], plan_graph_hash=revision["plan_graph_hash"],
                connection_id=step["connection_id"], attempt=claim["attempt"],
                now_ts=now,
            )
        except Exception as exc:
            raise _pre_dispatch_rejection(exc)
        status, body = self.broker.execute(lease, binding, step["input"])
        if status != 200:
            _raise_for_broker_failure(
                status, body, step["effect"],
                capability_retry_policy(step["capability_id"], step["effect"]),
            )
        return {
            "receipt": body.get("receipt", {}),
            "output": body.get("receipt", {}),
            "attestation": body.get("execution_attestation"),
        }
