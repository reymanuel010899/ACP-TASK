"""Durable, one-step-at-a-time workflow scheduler."""

import time


class RetryableStepError(Exception):
    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


class AmbiguousStepError(Exception):
    pass


class WorkflowExecutor:
    def __init__(self, repository, dispatcher, policy=None, clock=None, lease_ttl=60):
        self.repository = repository
        self.dispatcher = dispatcher
        self.policy = policy or (lambda _step: True)
        self.clock = clock or time.time
        self.lease_ttl = int(lease_ttl)

    def run_next(self, workflow_run_id, revision_id, tenant_id, worker_id):
        revision = self.repository.get_revision(workflow_run_id, revision_id, tenant_id)
        if revision is None:
            raise ValueError("workflow revision not found")
        effects = {step["effect"] for step in revision["steps"]}
        authorized = all(self.repository.is_step_authorized(
            workflow_run_id, revision_id, tenant_id, revision["plan_graph_hash"],
            effect, int(self.clock()),
        ) for effect in effects) if hasattr(self.repository, "is_step_authorized") else self.repository.is_revision_approved(
            workflow_run_id, revision_id, tenant_id, revision["plan_graph_hash"], int(self.clock())
        )
        if not authorized:
            return {"status": "needs_approval"}
        claim = self.repository.claim_ready_step(
            workflow_run_id, revision_id, tenant_id, worker_id,
            int(self.clock()), self.lease_ttl,
        )
        if claim is None:
            current = self.repository.get_revision(workflow_run_id, revision_id, tenant_id)
            states = [step["execution_status"] for step in current["steps"]]
            return {"status": "complete" if states and all(s == "completed" for s in states) else "blocked"}
        revision = self.repository.get_revision(
            workflow_run_id, revision_id, tenant_id
        )
        step = next(item for item in revision["steps"] if item["step_id"] == claim["step_id"])
        step = dict(step)
        step["approved_input"] = step["input"]
        try:
            step["input"] = self._resolve_input(
                step["input"], revision, revision_id, tenant_id
            )
        except (KeyError, StopIteration, TypeError, IndexError) as exc:
            self.repository.pause_by_policy(
                revision_id, step["step_id"], tenant_id,
                "workflow input reference is unavailable: %s" % exc,
            )
            self.repository.finish_claim_lease(
                claim, tenant_id, int(self.clock()), consumed=False
            )
            return {"status": "needs_replan", "step_id": step["step_id"]}
        if not self.policy(step):
            self.repository.pause_by_policy(revision_id, step["step_id"], tenant_id, "dispatch policy disabled")
            self.repository.finish_claim_lease(
                claim, tenant_id, int(self.clock()), consumed=False
            )
            return {"status": "paused_by_policy", "step_id": step["step_id"]}
        try:
            result = self.dispatcher(step, claim)
        except AmbiguousStepError as exc:
            self.repository.mark_execution_unknown(revision_id, step["step_id"], tenant_id, str(exc))
            self.repository.finish_claim_lease(claim, tenant_id, int(self.clock()), consumed=True)
            return {"status": "execution_unknown", "step_id": step["step_id"]}
        except RetryableStepError as exc:
            delay = exc.retry_after or min(300, 2 ** int(claim["attempt"]))
            self.repository.release_for_retry(
                revision_id, step["step_id"], tenant_id, str(exc),
                int(self.clock()) + max(1, int(delay)),
            )
            self.repository.finish_claim_lease(claim, tenant_id, int(self.clock()), consumed=False)
            return {"status": "retry_wait", "step_id": step["step_id"]}
        except PermissionError as exc:
            self.repository.pause_by_policy(revision_id, step["step_id"], tenant_id, str(exc))
            self.repository.finish_claim_lease(claim, tenant_id, int(self.clock()), consumed=False)
            return {"status": "blocked_connection", "step_id": step["step_id"]}
        except Exception as exc:
            self.repository.mark_execution_unknown(
                revision_id, step["step_id"], tenant_id,
                "unexpected dispatch outcome: %s" % exc,
            )
            self.repository.finish_claim_lease(claim, tenant_id, int(self.clock()), consumed=True)
            return {"status": "execution_unknown", "step_id": step["step_id"]}
        receipt = result.get("receipt", {})
        attestation = result.get("attestation")
        self.repository.persist_completion(
            revision_id, step["step_id"], tenant_id, claim["attempt"],
            receipt, attestation, int(self.clock()), output=result.get("output", {}),
        )
        self.repository.finish_claim_lease(claim, tenant_id, int(self.clock()), consumed=True)
        return {"status": "step_completed", "step_id": step["step_id"]}

    def run_until_blocked(self, workflow_run_id, revision_id, tenant_id, worker_id):
        while True:
            result = self.run_next(workflow_run_id, revision_id, tenant_id, worker_id)
            if result["status"] != "step_completed":
                return result

    def _resolve_input(self, value, revision, revision_id, tenant_id):
        if isinstance(value, dict):
            if set(value) == {"$ref"}:
                parts = value["$ref"].split(".")
                source = next(item for item in revision["steps"] if item["step_id"] == parts[0])
                material = source["output"] if parts[1] == "output" else self.repository.get_step_receipt(revision_id, parts[0], tenant_id)
                for part in parts[2:]:
                    material = material[part]
                return material
            return {key: self._resolve_input(item, revision, revision_id, tenant_id) for key, item in value.items()}
        if isinstance(value, list):
            return [self._resolve_input(item, revision, revision_id, tenant_id) for item in value]
        return value
