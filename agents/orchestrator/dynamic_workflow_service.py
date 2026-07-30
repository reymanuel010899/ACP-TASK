"""Application service that turns a goal into an approval-ready revision."""

import hashlib
import json
import time

from agents.orchestrator.planner import DynamicPlanner, PlanCompiler
from libs.integrations.catalog import ConnectionCapabilitySnapshot


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class DynamicWorkflowService:
    def __init__(self, brain, definitions, connection_repository, workflow_repository,
                 rollout_version="production-v1", shadow_mode=True, clock=None):
        self.brain = brain
        self.definitions = tuple(definitions)
        self.connections = connection_repository
        self.workflows = workflow_repository
        self.rollout_version = rollout_version
        self.shadow_mode = bool(shadow_mode)
        self.clock = clock or time.time

    def plan(self, tenant_id, principal_id, goal, context=None):
        installations = self.connections.list_installations(tenant_id, principal_id)
        connection_labels = {
            item["connection_id"]: (
                item.get("team_name") or item.get("provider_account")
                or item.get("team_id") or item["connection_id"]
            ) for item in installations
        }
        snapshots = []
        for connection in installations:
            if connection.get("status") != "connected":
                continue
            enabled = set(connection.get("enabled_capabilities") or ())
            for definition in self.definitions:
                if definition.capability_id not in enabled:
                    continue
                snapshots.append(ConnectionCapabilitySnapshot(
                    connection_id=connection["connection_id"], tenant_id=tenant_id,
                    capability_id=definition.capability_id,
                    capability_version=definition.version,
                    credential_version=int(connection.get("credential_version") or 0),
                    effective_scopes=frozenset(connection.get("granted_scopes") or ()),
                    health="healthy", rollout_version=self.rollout_version,
                ))
        compiler = PlanCompiler(self.definitions, snapshots, self.rollout_version)
        compiled = DynamicPlanner(self.brain, compiler, self.shadow_mode).plan(
            goal, {**(context or {}), "tenant_id": tenant_id}
        )
        if compiled["tenant_id"] != tenant_id:
            raise ValueError("planner tenant binding changed")
        now = int(self.clock())
        run = self.workflows.create_run(tenant_id, principal_id, _hash(goal), now)
        persisted_steps = []
        for step in compiled["steps"]:
            persisted_steps.append({
                **step,
                "input_hash": _hash(step["input"]),
            })
        revision = self.workflows.create_revision(
            run["workflow_run_id"], tenant_id, compiled["plan_graph_hash"],
            persisted_steps, now,
        )
        disclosures = {item["step_id"]: item for item in compiled["disclosures"]}
        definitions = {
            (item.capability_id, item.version): item for item in self.definitions
        }
        preview = {
            "workflowId": run["workflow_run_id"],
            "revisionId": revision["workflow_revision_id"],
            "revision": revision["revision_number"],
            "outcome": compiled["goal"],
            "steps": [{
                "id": step["step_id"],
                "label": step["capability_id"],
                "provider": step["provider"],
                "account": connection_labels.get(step["connection_id"], step["connection_id"]),
                "effect": step["effect"],
                "effectFields": {
                    field: step["input"].get(field)
                    for field in definitions[
                        (step["capability_id"], step["capability_version"])
                    ].preview_fields
                    if field in step["input"]
                },
                "disclosure": (
                    "%s → %s (%s)" % (
                        disclosures[step["step_id"]]["source"],
                        disclosures[step["step_id"]]["destination"],
                        disclosures[step["step_id"]]["classification"],
                    ) if step["step_id"] in disclosures else None
                ),
            } for step in compiled["steps"]],
            "blockers": [item.get("question") or item.get("prompt") or item.get("kind")
                         for item in compiled["blockers"]],
        }
        return {"run": run, "revision": revision, "plan": compiled, "preview": preview}
