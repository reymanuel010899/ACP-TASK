"""Application service that turns a goal into an approval-ready revision."""

import hashlib
import json
import time

from agents.orchestrator.planner import DynamicPlanner, PlanCompiler
from agents.orchestrator.slack_conversation import SlackConversationCoordinator
from libs.integrations.catalog import ConnectionCapabilitySnapshot


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class DynamicWorkflowService:
    def __init__(self, brain, definitions, connection_repository, workflow_repository,
                 rollout_version="production-v1", shadow_mode=True, clock=None,
                 conversation_store=None):
        self.brain = brain
        self.definitions = tuple(definitions)
        self.connections = connection_repository
        self.workflows = workflow_repository
        self.rollout_version = rollout_version
        self.shadow_mode = bool(shadow_mode)
        self.clock = clock or time.time
        self.conversation_store = conversation_store
        self.slack_coordinator = SlackConversationCoordinator()

    def coordinate_slack_turn(
        self, tenant_id, principal_id, text, conversation_id=None,
        channels=None, users=None,
    ):
        """Interpret and ground one turn without compiling unresolved authority."""
        active = None
        if conversation_id and self.conversation_store is not None:
            active = self.conversation_store.get(
                conversation_id, tenant_id, principal_id
            )
        installations = self._tenant_installations(tenant_id, principal_id)
        result = self.slack_coordinator.coordinate(
            text, active_state=active, installations=installations,
            channels=channels, users=users,
        )
        if conversation_id and active is None and result.turn.refers_to_active_target:
            return {
                "state": "expired", "conversation_id": conversation_id,
                "need": result.need,
                "message": (
                    "Esta conversación expiró; vuelve a indicar el destino."
                    if result.turn.locale == "es"
                    else "This conversation expired; please name the target again."
                ),
            }
        payload = result.model_dump()
        if self.conversation_store is not None:
            if active is None:
                active = self.conversation_store.create(
                    tenant_id, principal_id, conversation_id,
                    locale=result.turn.locale,
                )
                conversation_id = active["conversation_id"]
            updates = {
                key: value for key, value in result.resolved.items()
                if key in {
                    "active_connection", "active_channel", "active_person",
                    "active_thread", "read_period", "pending_draft",
                }
            }
            updates.update(status=result.state, locale=result.turn.locale,
                           operation=result.turn.operation)
            self.conversation_store.update(
                conversation_id, tenant_id, principal_id, **updates
            )
            if result.need:
                self.conversation_store.record_need(
                    conversation_id, tenant_id, principal_id, result.need
                )
            payload["conversation_id"] = conversation_id
        return payload

    def _tenant_installations(self, tenant_id, principal_id):
        if hasattr(self.connections, "list_tenant_installations"):
            return self.connections.list_tenant_installations(tenant_id, "slack")
        if hasattr(self.connections, "list_for_tenant"):
            return self.connections.list_for_tenant(tenant_id, "slack")
        return self.connections.list_installations(tenant_id, principal_id)

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
