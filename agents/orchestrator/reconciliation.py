"""Narrow reconciliation for provider calls with an ambiguous outcome."""


def reconcile_unknown_action(repository, binding, provider_lookup, now_ts):
    proposal = repository.get_by_idempotency_key(binding["idempotency_key"])
    if proposal is None or proposal.get("status") != "execution_unknown":
        return {"status": "not_unknown"}
    receipt = provider_lookup(binding)
    if not isinstance(receipt, dict):
        return {"status": "execution_unknown", "requires_resolution": True}
    repository.complete_execution(
        proposal["proposal_id"], proposal["version"], receipt, now_ts
    )
    return {"status": "completed", "receipt": receipt}


class WorkflowReconciler(object):
    """Drive every unknown write to a verdict, or to a named human decision.

    Without this runner an unknown outcome is terminal in practice: the step
    never leaves `execution_unknown`, and the action proposal it belongs to
    keeps refusing every later attempt on that step. Asking the provider what
    happened is the only safe move for a non-repeatable effect, because a
    question cannot make the effect happen twice.
    """

    RETRY_SECONDS = 60
    MAX_ATTEMPTS = 5

    def __init__(self, workflows, actions, reconcilers=None,
                 worker_id="reconciler", retry_seconds=None, max_attempts=None):
        self.workflows = workflows
        self.actions = actions
        # Keyed by capability family, e.g. "slack" for "slack.message.send".
        self.reconcilers = dict(reconcilers or {})
        self.worker_id = worker_id
        self.retry_seconds = int(retry_seconds or self.RETRY_SECONDS)
        self.max_attempts = int(max_attempts or self.MAX_ATTEMPTS)

    def run_once(self, now_ts, limit=50):
        verdicts = []
        for step in self.workflows.list_unresolved_write_steps(now_ts, limit):
            verdict = self.reconcile(step, now_ts)
            if verdict is not None:
                verdicts.append(verdict)
        return verdicts

    def reconcile(self, step, now_ts):
        if not self.workflows.claim_unresolved_write_step(
            step["workflow_revision_id"], step["step_id"], step["tenant_id"],
            step["attempt"], self.worker_id, now_ts, self.retry_seconds,
        ):
            return None
        observed = self._ask_provider(step, now_ts)
        status = observed.get("execution_status")
        if status == "completed":
            return self._apply_completion(step, observed, now_ts)
        if status == "queued":
            return self._apply_absence(step, observed, now_ts)
        return self._defer(step, observed, now_ts)

    def _ask_provider(self, step, now_ts):
        family = str(step.get("capability_id") or "").split(".")[0]
        reconciler = self.reconcilers.get(family)
        if reconciler is None:
            return {
                "execution_status": "execution_unknown",
                "reason": "no reconciler is registered for %s" % (family or "?"),
            }
        try:
            return reconciler.reconcile(dict(step, reconciled_at=now_ts)) or {}
        except Exception as exc:
            # An unreachable provider proves nothing, so the effect stays
            # unknown rather than being guessed in either direction.
            return {
                "execution_status": "execution_unknown",
                "reason": "provider was unreachable: %s" % type(exc).__name__,
            }

    def _apply_completion(self, step, observed, now_ts):
        if not isinstance(observed.get("receipt"), dict) or not isinstance(
            observed.get("attestation"), dict
        ):
            # A completion nobody can evidence is not a completion.
            return self._defer(step, dict(
                observed,
                reason="provider confirmed the effect without a signed receipt",
            ), now_ts)
        applied = self.workflows.apply_reconciliation(
            step["workflow_revision_id"], step["step_id"], step["tenant_id"],
            step["attempt"], dict(observed, reconciled_at=now_ts),
        )
        proposal = self._proposal(step)
        if proposal is not None:
            self.actions.complete_execution(
                proposal["proposal_id"], proposal["version"],
                observed.get("receipt") or {}, now_ts,
            )
        return {
            "status": "completed", "applied": bool(applied),
            "step_id": step["step_id"],
            "workflow_revision_id": step["workflow_revision_id"],
            "provider_id": observed.get("provider_id"),
        }

    def _apply_absence(self, step, observed, now_ts):
        applied = self.workflows.apply_reconciliation(
            step["workflow_revision_id"], step["step_id"], step["tenant_id"],
            step["attempt"], dict(observed, reconciled_at=now_ts),
        )
        proposal = self._proposal(step)
        if proposal is not None:
            self.actions.resolve_unknown_as_absent(
                proposal["proposal_id"], proposal["version"],
                "reconciliation proved no effect occurred", now_ts,
            )
        return {
            "status": "queued", "applied": bool(applied),
            "step_id": step["step_id"],
            "workflow_revision_id": step["workflow_revision_id"],
        }

    def _defer(self, step, observed, now_ts):
        attempts = int(step.get("reconcile_attempts") or 0) + 1
        exhausted = attempts >= self.max_attempts
        reason = observed.get("reason") or "reconciliation is unresolved"
        retry_after = int(observed.get("retry_after") or self.retry_seconds)
        self.workflows.defer_reconciliation(
            step["workflow_revision_id"], step["step_id"], step["tenant_id"],
            step["attempt"],
            ("awaiting human resolution: %s" % reason) if exhausted else reason,
            int(now_ts) + (self.retry_seconds if exhausted else retry_after),
        )
        return {
            "status": "execution_unknown",
            "requires_resolution": True,
            "exhausted": exhausted,
            "reason": reason,
            "step_id": step["step_id"],
            "workflow_revision_id": step["workflow_revision_id"],
        }

    def _proposal(self, step):
        if self.actions is None:
            return None
        return self.actions.get_by_idempotency_key(
            "workflow:%s:%s:attempt:%s" % (
                step["workflow_revision_id"], step["step_id"], step["attempt"]
            )
        )
