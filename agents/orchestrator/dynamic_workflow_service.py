"""Application service that turns a goal into an approval-ready revision."""

import hashlib
import json
import time

from agents.orchestrator.planner import DynamicPlanner, PlanCompiler, descriptor_hash
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
        effects = {step["effect"] for step in persisted_steps}
        if effects == {"read"} and hasattr(self.workflows, "authorize_requested_read"):
            self.workflows.authorize_requested_read(
                run["workflow_run_id"], revision["workflow_revision_id"],
                tenant_id, compiled["plan_graph_hash"], principal_id, now,
            )
            revision = self.workflows.get_revision(
                run["workflow_run_id"], revision["workflow_revision_id"], tenant_id
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

    def present_read_once(
        self, conversation_id, tenant_id, principal_id, presenter,
        question, evidence, locale,
    ):
        if self.conversation_store is None:
            raise ValueError("conversation store is required")
        current = self.conversation_store.get(
            conversation_id, tenant_id, principal_id
        )
        if current is None:
            raise KeyError("conversation unavailable")
        if current.get("presentation") is not None:
            return current["presentation"]
        presentation = presenter.present(question, evidence, locale)
        stored = self.conversation_store.present(
            conversation_id, tenant_id, principal_id, presentation
        )
        return stored["presentation"]

    def materialize_slack_write(
        self, conversation_id, tenant_id, principal_id, capability_id, text,
    ):
        if capability_id not in {
            "slack.message.send", "slack.thread.reply", "slack.direct_message.send"
        }:
            raise ValueError("unsupported Slack write capability")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("exact message text is required")
        conversation = self.conversation_store.get(
            conversation_id, tenant_id, principal_id
        )
        if conversation is None:
            raise KeyError("conversation unavailable")
        connection_ref = conversation.get("active_connection") or {}
        connection = next((item for item in self._tenant_installations(
            tenant_id, principal_id
        ) if item.get("connection_id") == connection_ref.get("id")), None)
        if connection is None or connection.get("status") != "connected":
            raise ValueError("Slack connection is unavailable")
        definition = next((item for item in self.definitions
                           if item.capability_id == capability_id), None)
        if definition is None or capability_id not in set(
            connection.get("enabled_capabilities") or ()
        ) or not definition.required_scopes.issubset(set(
            connection.get("granted_scopes") or ()
        )):
            raise PermissionError("missing_scope:%s" % (
                sorted(definition.required_scopes)[0] if definition else "unknown"
            ))
        payload = {"text": text}
        label = None
        entity_version = None
        if capability_id == "slack.message.send":
            target = conversation.get("active_channel") or {}
            payload["channel_id"] = target.get("id")
            label = "#%s" % target.get("name") if target.get("name") else None
            entity_version = _hash(target)
        elif capability_id == "slack.thread.reply":
            thread = conversation.get("active_thread") or {}
            channel = conversation.get("active_channel") or {}
            payload.update(channel_id=thread.get("channel_id") or channel.get("id"),
                           thread_ts=thread.get("thread_ts"))
            label = "#%s thread" % channel.get("name") if channel.get("name") else "Slack thread"
            entity_version = _hash({"channel": channel, "thread": thread})
        else:
            target = conversation.get("active_person") or {}
            payload["user_id"] = target.get("id")
            label = target.get("display_name") or target.get("real_name") or target.get("handle")
            entity_version = _hash(target)
        if any(not isinstance(value, str) or not value for value in payload.values()):
            raise ValueError("Slack write target is unresolved")
        now = int(self.clock())
        run_id = conversation.get("workflow_run_id")
        run = self.workflows.get_run(run_id, tenant_id) if run_id else None
        if run is None:
            run = self.workflows.create_run(tenant_id, principal_id, _hash("slack-write"), now)
        step = {
            "step_id": "slack-write", "capability_id": capability_id,
            "capability_version": definition.version,
            "connection_id": connection["connection_id"],
            "descriptor_snapshot_hash": descriptor_hash(definition),
            "credential_version": int(connection.get("credential_version") or 0),
            "input": payload, "input_hash": _hash(payload), "depends_on": [],
            "effect": "write",
        }
        binding = {
            "connection_id": connection["connection_id"],
            "credential_version": int(connection.get("credential_version") or 0),
            "entity_version": entity_version, "destination_label": label,
            "payload_hash": _hash(payload), "capability_id": capability_id,
        }
        graph_hash = _hash({"tenant_id": tenant_id, "steps": [step], "binding": binding})
        revision = self.workflows.create_revision(
            run["workflow_run_id"], tenant_id, graph_hash, [step], now
        )
        draft = {
            **binding, "workflow_run_id": run["workflow_run_id"],
            "workflow_revision_id": revision["workflow_revision_id"],
            "plan_graph_hash": graph_hash, "text": text,
        }
        draft["draft_hash"] = _hash(draft)
        self.conversation_store.update(
            conversation_id, tenant_id, principal_id,
            status="awaiting_approval", pending_draft=draft,
            workflow_run_id=run["workflow_run_id"],
            workflow_revision_id=revision["workflow_revision_id"],
        )
        return dict(draft)

    def approve_slack_draft(
        self, conversation_id, tenant_id, principal_id, draft_hash,
    ):
        conversation = self.conversation_store.get(
            conversation_id, tenant_id, principal_id
        )
        draft = (conversation or {}).get("pending_draft") or {}
        if not draft or draft.get("draft_hash") != draft_hash:
            raise ValueError("draft binding changed")
        capability_id = draft.get("capability_id")
        if capability_id == "slack.message.send":
            current_entity_version = _hash(conversation.get("active_channel") or {})
        elif capability_id == "slack.thread.reply":
            current_entity_version = _hash({
                "channel": conversation.get("active_channel") or {},
                "thread": conversation.get("active_thread") or {},
            })
        else:
            current_entity_version = _hash(conversation.get("active_person") or {})
        if current_entity_version != draft.get("entity_version"):
            raise ValueError("draft binding changed")
        connection = next((item for item in self._tenant_installations(
            tenant_id, principal_id
        ) if item.get("connection_id") == draft.get("connection_id")), None)
        if (
            connection is None or connection.get("status") != "connected"
            or int(connection.get("credential_version") or 0) != draft.get("credential_version")
        ):
            raise ValueError("draft binding changed")
        self.workflows.record_approval(
            draft["workflow_run_id"], draft["workflow_revision_id"], tenant_id,
            draft["plan_graph_hash"], principal_id, int(self.clock()),
        )
        self.conversation_store.update(
            conversation_id, tenant_id, principal_id, status="executing"
        )
        return dict(draft)

    def complete_slack_write(
        self, conversation_id, tenant_id, principal_id, locale="es"
    ):
        presentation = {
            "locale": locale,
            "answer": "Mensaje enviado" if locale == "es" else "Message sent",
            "citations": [], "partial": False,
        }
        self.conversation_store.present(
            conversation_id, tenant_id, principal_id, presentation
        )
        self.conversation_store.update(
            conversation_id, tenant_id, principal_id,
            status="succeeded", pending_draft=None,
        )
        return presentation
