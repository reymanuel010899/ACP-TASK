"""Application service that turns a goal into an approval-ready revision."""

import hashlib
import json
import time

from agents.orchestrator.planner import DynamicPlanner, PlanCompiler, descriptor_hash
from agents.orchestrator.slack_conversation import SlackConversationCoordinator
from agents.orchestrator.slack_operations import (
    load_slack_operations,
)
from libs.integrations.catalog import ConnectionCapabilitySnapshot


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class DynamicWorkflowService:
    def __init__(self, brain, definitions, connection_repository, workflow_repository,
                 rollout_version="production-v1", shadow_mode=True, clock=None,
                 conversation_store=None, conversational_reads_enabled=True,
                 slack_writes_enabled=True, slack_dms_enabled=True,
                 slack_policy_visible=None, slack_family_flags=None):
        self.brain = brain
        self.definitions = tuple(definitions)
        self.connections = connection_repository
        self.workflows = workflow_repository
        self.rollout_version = rollout_version
        self.shadow_mode = bool(shadow_mode)
        self.clock = clock or time.time
        self.conversation_store = conversation_store
        self.conversational_reads_enabled = bool(conversational_reads_enabled)
        self.slack_writes_enabled = bool(slack_writes_enabled)
        self.slack_dms_enabled = bool(slack_dms_enabled)
        self.slack_policy_visible = slack_policy_visible
        self.slack_family_flags = dict(slack_family_flags or {})
        self.slack_coordinator = SlackConversationCoordinator()
        slack_definitions = tuple(
            item for item in self.definitions if item.provider == "slack"
        )
        self.slack_operation_registry = (
            load_slack_operations(slack_definitions)
            if slack_definitions else None
        )

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
        if channels is None and hasattr(self.connections, "list_slack_channels"):
            channels = self.connections.list_slack_channels(tenant_id, principal_id)
        if users is None and hasattr(self.connections, "list_slack_users"):
            users = self.connections.list_slack_users(tenant_id, principal_id)
        interpretation = None
        projection = ()
        if self.slack_operation_registry is not None and hasattr(
            self.brain, "understand_slack"
        ):
            projection = self._slack_operation_projection(installations)
            interpretation = self.brain.understand_slack(text, {
                "slack_operation_projection": projection,
                "active_conversation": active or {},
            })
            limitation = self._interpretation_limitation(
                text, interpretation, installations, projection
            )
            if limitation is not None:
                return limitation
        result = self.slack_coordinator.coordinate(
            text, active_state=active, installations=installations,
            channels=channels, users=users, interpretation=interpretation,
        )
        disabled_feature = self._disabled_slack_feature(result.turn.operation)
        if disabled_feature:
            return {
                "state": "retryable_failure",
                "error": {"code": "feature_disabled"},
                "recovery": {
                    "action": "contact_admin", "feature": disabled_feature,
                },
            }
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
        if interpretation is not None:
            proposal = interpretation.model_dump()
            payload["slack_interpretation"] = proposal
            payload["compound_operations"] = proposal["operations"]
            payload["dependencies"] = proposal["dependencies"]
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
                    "active_thread", "active_message", "active_file",
                    "active_reaction", "read_period", "pending_draft",
                }
            }
            prior_refs = {
                item.get("slot"): item
                for item in (active.get("entity_refs") or [])
                if isinstance(item, dict) and item.get("slot")
            }
            entity_refs = self._persist_grounded_slack_entities(
                active, result.resolved, installations,
                "brain" if interpretation is not None else "deterministic",
            )
            if entity_refs:
                updates["entity_refs"] = entity_refs
            if interpretation is not None:
                proposal = interpretation.model_dump()
                updates["operation_candidates"] = proposal["operations"]
                updates["slot_state"] = proposal["slots"]
                updates["dependencies"] = proposal["dependencies"]
                updates["blockers"] = proposal["blockers"]
                updates["effect_candidates"] = proposal["operations"]
                known_inputs = dict(active.get("known_inputs") or {})
                for slot in proposal["slots"]:
                    known_inputs[slot["name"]] = slot["value"]
                updates["known_inputs"] = known_inputs
                current_refs = {
                    item.get("slot"): item
                    for item in entity_refs
                    if isinstance(item, dict) and item.get("slot")
                }
                corrections = list(active.get("corrections") or [])
                slot_names = {
                    "channel": "active_channel",
                    "person": "active_person",
                    "thread": "active_thread",
                    "message": "active_message",
                    "file": "active_file",
                    "reaction": "active_reaction",
                    "workspace": "active_connection",
                }
                for correction in proposal["corrections"]:
                    slot = slot_names.get(correction["slot"])
                    previous = prior_refs.get(slot) or {}
                    replacement = current_refs.get(slot) or {}
                    corrections.append({
                        **correction,
                        "recorded_at": int(self.clock()),
                        "base_state_version": active["state_version"],
                        "previous_entity_ref_id": previous.get("entity_ref_id"),
                        "replacement_entity_ref_id": replacement.get(
                            "entity_ref_id"
                        ),
                    })
                updates["corrections"] = corrections
            persisted_status = "succeeded" if result.state == "completed" else result.state
            updates.update(status=persisted_status, locale=result.turn.locale,
                           operation=result.turn.operation, blocking_need=None)
            self.conversation_store.update(
                conversation_id, tenant_id, principal_id, **updates
            )
            if result.need:
                self.conversation_store.record_need(
                    conversation_id, tenant_id, principal_id, result.need
                )
            payload["conversation_id"] = conversation_id
        return payload

    def advance_slack_turn(self, conversation_id, tenant_id, principal_id,
                           text, turn_payload):
        """Compile a fully grounded turn; unresolved turns remain intake-only."""
        need = turn_payload.get("need") or {}
        turn = turn_payload.get("turn") or {}
        query = turn.get("channel_name") if need.get("field") == "channel" else turn.get("person_name")
        if turn_payload.get("state") == "needs_input" and query and need.get("field") in {"channel", "person"}:
            return self._start_slack_entity_resolution(
                conversation_id, tenant_id, principal_id, text, turn, need["field"], query
            )
        if turn_payload.get("state") != "resolving":
            return turn_payload
        if len(turn_payload.get("compound_operations") or ()) > 1:
            return {
                "state": "retryable_failure", "conversation_id": conversation_id,
                "error": {"code": "compound_execution_unavailable"},
                "recovery": {"action": "wait_for_compound_rollout"},
                "compound_operations": turn_payload["compound_operations"],
                "dependencies": turn_payload.get("dependencies") or [],
            }
        resolved = turn_payload.get("resolved") or {}
        operation = turn.get("operation")
        if operation in {"post", "reply", "dm"}:
            capability = {
                "post": "slack.message.send",
                "reply": "slack.thread.reply",
                "dm": "slack.direct_message.send",
            }[operation]
            draft = self.materialize_slack_write(
                conversation_id, tenant_id, principal_id, capability,
                resolved.get("message_text") or turn.get("message_text"),
            )
            return {
                "state": "awaiting_approval", "conversation_id": conversation_id,
                "draft": draft,
            }
        if operation in {"read", "summarize", "list_channels", "list_private_channels"}:
            goal = ({
                "list_channels": "Lista los canales públicos de Slack",
                "list_private_channels": "Lista los canales privados de Slack",
            }.get(operation, text))
            workflow = self.plan(
                tenant_id, principal_id, goal,
                {"slack_resolution": resolved},
            )
            self.conversation_store.update(
                conversation_id, tenant_id, principal_id, status="retrieving",
                workflow_run_id=workflow["run"]["workflow_run_id"],
                workflow_revision_id=workflow["revision"]["workflow_revision_id"],
            )
            return {
                "state": "retrieving", "conversation_id": conversation_id,
                "workflow": workflow["preview"],
            }
        return turn_payload

    def _start_slack_entity_resolution(self, conversation_id, tenant_id,
                                       principal_id, text, turn, field, query):
        capability_id = "slack.channels.list" if field == "channel" else "slack.users.list"
        conversation = self.conversation_store.get(conversation_id, tenant_id, principal_id)
        connection_id = ((conversation or {}).get("active_connection") or {}).get("id")
        connection = next((item for item in self._tenant_installations(tenant_id, principal_id)
                           if item.get("connection_id") == connection_id), None)
        definition = next((item for item in self.definitions
                           if item.capability_id == capability_id), None)
        if not connection or not definition or capability_id not in set(
            connection.get("enabled_capabilities") or ()
        ) or not definition.required_scopes.issubset(set(connection.get("granted_scopes") or ())):
            required = sorted(definition.required_scopes)[0] if definition else "unknown"
            raise PermissionError("missing_scope:%s" % required)
        now = int(self.clock())
        resolver_run = self._reserve_slack_resolver_run(
            conversation, conversation_id, tenant_id, principal_id,
            connection_id, field, query, now,
        )
        run, revision = self._dispatch_slack_resolver_page(
            tenant_id, principal_id, field, capability_id, definition,
            connection_id, connection, None, now,
        )
        if resolver_run is not None:
            self.workflows.attach_slack_resolver_workflow(
                resolver_run["resolver_run_id"], tenant_id,
                run["workflow_run_id"], revision["workflow_revision_id"], now,
            )
        self.conversation_store.update(
            conversation_id, tenant_id, principal_id, status="retrieving",
            blocking_need=None, workflow_run_id=run["workflow_run_id"],
            workflow_revision_id=revision["workflow_revision_id"],
            resolution_request={"field": field, "query": query,
                                "text": text, "turn": turn,
                                "locale": turn.get("locale", "es"),
                                "resolver_run_id": (resolver_run or {}).get(
                                    "resolver_run_id"
                                )},
        )
        return {"state": "retrieving", "conversation_id": conversation_id,
                "workflow": {"workflowId": run["workflow_run_id"],
                             "revisionId": revision["workflow_revision_id"]}}

    def _reserve_slack_resolver_run(
        self, conversation, conversation_id, tenant_id, principal_id,
        connection_id, field, query, now,
    ):
        """Reserve the durable run that owns this resolution's pagination."""
        if not hasattr(self.workflows, "start_slack_resolver_run"):
            return None
        return self.workflows.start_slack_resolver_run(
            conversation_id, tenant_id, principal_id, connection_id,
            "channel" if field == "channel" else "user",
            _hash({"field": field, "query": query}),
            int((conversation or {}).get("state_version") or 1), now,
        )

    def _dispatch_slack_resolver_page(
        self, tenant_id, principal_id, field, capability_id, definition,
        connection_id, connection, cursor, now,
    ):
        run = self.workflows.create_run(
            tenant_id, principal_id, _hash("resolve:%s" % field), now
        )
        payload = {"limit": 200}
        if cursor:
            payload["cursor"] = cursor
        step = {
            "step_id": "resolve-slack-%s" % field,
            "capability_id": capability_id, "capability_version": definition.version,
            "connection_id": connection_id,
            "descriptor_snapshot_hash": descriptor_hash(definition),
            "credential_version": int(connection.get("credential_version") or 0),
            "input": payload, "input_hash": _hash(payload), "depends_on": [], "effect": "read",
        }
        graph_hash = _hash({"tenant_id": tenant_id, "steps": [step]})
        revision = self.workflows.create_revision(run["workflow_run_id"], tenant_id,
                                                  graph_hash, [step], now)
        self.workflows.authorize_requested_read(
            run["workflow_run_id"], revision["workflow_revision_id"], tenant_id,
            graph_hash, principal_id, now,
        )
        return run, revision

    def apply_slack_resolver_completion(self, tenant_id, conversation_id,
                                        payload, now=None):
        """Continue a resolved turn from its durable event, never from a GET."""
        principal_id = payload.get("principal_id")
        conversation = self.conversation_store.get(
            conversation_id, tenant_id, principal_id
        ) if self.conversation_store and principal_id else None
        if conversation is None:
            return False
        request = conversation.get("resolution_request") or {}
        if request.get("resolver_run_id") != payload.get("resolver_run_id"):
            return False
        if conversation.get("status") != "resolving":
            return False
        self.resume_resolved_slack_turn(conversation)
        return True

    def continue_slack_resolver_run(self, run, now=None):
        """Dispatch the next durable page after completion or a restart."""
        cursor = run.get("cursor") or {}
        next_cursor = cursor.get("next")
        if not next_cursor or next_cursor in (cursor.get("consumed") or []):
            return False
        if cursor.get("dispatched") == next_cursor:
            return False
        conversation = self.conversation_store.get(
            run["conversation_id"], run["tenant_id"], run["principal_id"]
        ) if self.conversation_store else None
        if conversation is None:
            return False
        request = conversation.get("resolution_request") or {}
        if request.get("resolver_run_id") != run["resolver_run_id"]:
            return False
        field = request.get("field")
        capability_id = (
            "slack.channels.list" if field == "channel" else "slack.users.list"
        )
        connection = next((
            item for item in self._tenant_installations(
                run["tenant_id"], run["principal_id"]
            ) if item.get("connection_id") == run["connection_id"]
        ), None)
        definition = next((item for item in self.definitions
                           if item.capability_id == capability_id), None)
        if not connection or not definition:
            return False
        now = int(self.clock() if now is None else now)
        page_run, revision = self._dispatch_slack_resolver_page(
            run["tenant_id"], run["principal_id"], field, capability_id,
            definition, run["connection_id"], connection, next_cursor, now,
        )
        self.workflows.attach_slack_resolver_workflow(
            run["resolver_run_id"], run["tenant_id"],
            page_run["workflow_run_id"], revision["workflow_revision_id"],
            now, cursor_token=next_cursor,
        )
        self.conversation_store.update(
            run["conversation_id"], run["tenant_id"], run["principal_id"],
            status="retrieving",
            workflow_run_id=page_run["workflow_run_id"],
            workflow_revision_id=revision["workflow_revision_id"],
        )
        return True

    def resume_resolved_slack_turn(self, conversation):
        request = conversation.get("resolution_request") or {}
        text = request.get("text") or "Slack conversational request"
        channels = [conversation["active_channel"]] if conversation.get("active_channel") else []
        users = [conversation["active_person"]] if conversation.get("active_person") else []
        payload = self.coordinate_slack_turn(
            conversation["tenant_id"], conversation["principal_id"], text,
            conversation_id=conversation["conversation_id"], channels=channels, users=users,
        )
        result = self.advance_slack_turn(
            conversation["conversation_id"], conversation["tenant_id"],
            conversation["principal_id"], text, payload,
        )
        current = self.conversation_store.get(
            conversation["conversation_id"], conversation["tenant_id"],
            conversation["principal_id"],
        )
        if (current or {}).get("resolution_request") == request:
            self.conversation_store.update(
                conversation["conversation_id"], conversation["tenant_id"],
                conversation["principal_id"], resolution_request=None,
            )
        return result

    def _disabled_slack_feature(self, operation):
        if operation in {"read", "summarize", "list_channels", "list_private_channels"} and not self.conversational_reads_enabled:
            return "slack_conversational_reads"
        if operation in {"post", "reply", "dm"} and not self.slack_writes_enabled:
            return "slack_writes"
        if operation == "dm" and not self.slack_dms_enabled:
            return "slack_dms"
        return None

    def _slack_family_state(self):
        state = {
            "slack_connection_status": True,
            "slack_channel_discovery": self.conversational_reads_enabled,
            "slack_private_reads": self.conversational_reads_enabled,
            "slack_conversation_reads": self.conversational_reads_enabled,
            "slack_user_discovery": True,
            "slack_messaging": self.slack_writes_enabled,
            "slack_direct_messages": self.slack_writes_enabled and self.slack_dms_enabled,
            "slack_reactions": False,
        }
        state.update(self.slack_family_flags)
        return state

    @staticmethod
    def _runtime_slack_operation_ids():
        return frozenset({
            "slack.connection.status", "slack.channels.list",
            "slack.private_channels.list", "slack.conversation.read",
            "slack.conversation.summarize", "slack.message.send",
            "slack.thread.reply", "slack.direct_message.send",
        })

    def _policy_allows_slack_operation(self, operation):
        if operation.operation_id not in self._runtime_slack_operation_ids():
            return False
        if self.slack_policy_visible is None:
            return True
        try:
            return self.slack_policy_visible(operation) is True
        except Exception:
            return False

    def _slack_operation_projection(self, installations):
        connected = [
            item for item in installations if item.get("status") == "connected"
        ]
        installed = set()
        for connection in connected:
            enabled = set(connection.get("enabled_capabilities") or ())
            scopes = set(connection.get("granted_scopes") or ())
            for definition in self.definitions:
                if (
                    definition.provider == "slack"
                    and definition.capability_id in enabled
                    and definition.required_scopes.issubset(scopes)
                ):
                    installed.add(definition.capability_id)
        return self.slack_operation_registry.model_projection(
            installed, self._slack_family_state(), self._policy_allows_slack_operation,
        )

    def _interpretation_limitation(
        self, text, interpretation, installations, projection,
    ):
        proposed = [item.operation_id for item in interpretation.operations]
        visible = {item["operation_id"] for item in projection}
        if proposed:
            for operation_id in proposed:
                descriptor = self.slack_operation_registry.get(operation_id)
                if descriptor is None:
                    return self._slack_limitation(
                        "unsupported_operation", "choose_supported_operation",
                        operation_id=operation_id,
                    )
                if operation_id not in visible:
                    return self._operation_unavailable(descriptor, installations)
            return None
        alias = self.slack_operation_registry.lookup_alias(text)
        if alias is not None and alias.operation_id not in visible:
            return self._operation_unavailable(alias, installations)
        blockers = list(getattr(interpretation, "blockers", ()) or ())
        if blockers and blockers[0].kind == "unsupported_operation":
            return self._slack_limitation(
                "unsupported_operation", "choose_supported_operation",
            )
        return None

    def _operation_unavailable(self, descriptor, installations):
        if descriptor.operation_id not in self._runtime_slack_operation_ids():
            return self._slack_limitation(
                "operation_unavailable", "wait_for_family_rollout",
                operation_id=descriptor.operation_id,
            )
        families = self._slack_family_state()
        if families.get(descriptor.family_flag) is not True:
            return self._slack_limitation(
                "feature_disabled", "contact_admin", feature=descriptor.family_flag,
            )
        if not self._policy_allows_slack_operation(descriptor):
            return self._slack_limitation(
                "policy_denied", "contact_admin", operation_id=descriptor.operation_id,
            )
        connected = [item for item in installations if item.get("status") == "connected"]
        if descriptor.operation_kind != "local" and not connected:
            return self._slack_limitation(
                "connection_unavailable", "connect_slack",
                operation_id=descriptor.operation_id,
            )
        required = {
            step.capability_id for step in descriptor.capability_recipe
        }
        definitions = {
            item.capability_id: item for item in self.definitions
            if item.provider == "slack"
        }
        enabled_anywhere = any(
            required.issubset(set(item.get("enabled_capabilities") or ()))
            for item in connected
        )
        missing_scopes = sorted({
            scope
            for capability_id in required
            for scope in definitions[capability_id].required_scopes
            if not any(
                capability_id in set(item.get("enabled_capabilities") or ())
                and scope in set(item.get("granted_scopes") or ())
                for item in connected
            )
        })
        if enabled_anywhere and missing_scopes:
            return self._slack_limitation(
                "missing_scope", "upgrade_slack_scopes",
                operation_id=descriptor.operation_id, scopes=missing_scopes,
            )
        return self._slack_limitation(
            "capability_unavailable", "reconnect_or_enable_capability",
            operation_id=descriptor.operation_id,
        )

    @staticmethod
    def _slack_limitation(code, action, **details):
        return {
            "state": "retryable_failure",
            "error": {"code": code, **details},
            "recovery": {"action": action, **details},
        }

    def _tenant_installations(self, tenant_id, principal_id):
        if hasattr(self.connections, "list_tenant_installations"):
            return self.connections.list_tenant_installations(tenant_id, "slack")
        if hasattr(self.connections, "list_for_tenant"):
            return self.connections.list_for_tenant(tenant_id, "slack")
        return self.connections.list_installations(tenant_id, principal_id)

    def _persist_grounded_slack_entities(
        self, conversation, resolved, installations, matched_by,
    ):
        """Persist minimized provider-grounded refs without trusting model IDs."""
        existing = [
            dict(item) for item in (conversation.get("entity_refs") or [])
            if isinstance(item, dict) and item.get("slot")
        ]
        by_slot = {item["slot"]: item for item in existing}
        connection = resolved.get("active_connection") or conversation.get(
            "active_connection"
        ) or {}
        connection_id = connection.get("id")
        installation = next((
            item for item in installations
            if item.get("connection_id") == connection_id
        ), None)
        team_id = (installation or {}).get("team_id")
        if not connection_id or not team_id:
            return existing
        now = int(self.clock())
        stale_after = now + 300
        candidates = [(
            "active_connection", "workspace", str(team_id), {
                "id": str(team_id),
                "name": (installation or {}).get("team_name")
                or connection.get("label"),
                "domain": (installation or {}).get("team_domain"),
            },
        )]
        targets = (
            ("active_channel", "channel"),
            ("active_person", "user"),
            ("active_message", "message"),
            ("active_thread", "thread"),
            ("active_file", "file"),
            ("active_reaction", "reaction"),
        )
        for slot, kind in targets:
            value = resolved.get(slot)
            if not isinstance(value, dict):
                continue
            provider_entity_id = self._slack_provider_entity_id(kind, value)
            if provider_entity_id:
                candidates.append((slot, kind, provider_entity_id, value))
        for slot, kind, provider_entity_id, value in candidates:
            stored = self.workflows.store_slack_conversation_entity(
                conversation["conversation_id"], conversation["tenant_id"],
                conversation["principal_id"], kind, connection_id, team_id,
                provider_entity_id, value,
                {"source": "turn_grounding", "matched_by": matched_by},
                now, stale_after,
                expected_state_version=conversation["state_version"],
            )
            by_slot[slot] = {
                "slot": slot,
                "entity_kind": kind,
                "entity_ref_id": stored["entity_ref_id"],
                "entity_version": stored["entity_version"],
                "entity_hash": stored["entity_hash"],
                "connection_id": connection_id,
                "team_id": team_id,
                "observed_at": stored["observed_at"],
                "stale_after": stored["stale_after"],
            }
        return list(by_slot.values())

    @staticmethod
    def _slack_provider_entity_id(kind, value):
        if kind in {"channel", "user", "file"}:
            return value.get("id")
        if kind == "message":
            channel = value.get("channel_id") or value.get("channel")
            timestamp = value.get("ts") or value.get("message_ts")
            return "%s:%s" % (channel, timestamp) if channel and timestamp else None
        if kind == "thread":
            channel = value.get("channel_id") or value.get("channel")
            timestamp = value.get("thread_ts") or value.get("parent_ts")
            return "%s:%s" % (channel, timestamp) if channel and timestamp else None
        if kind == "reaction":
            channel = value.get("channel_id") or value.get("channel")
            timestamp = value.get("message_ts") or value.get("ts")
            name = value.get("name")
            return (
                "%s:%s:%s" % (channel, timestamp, name)
                if channel and timestamp and name else None
            )
        return None

    def plan(self, tenant_id, principal_id, goal, context=None):
        context = dict(context or {})
        installations = (
            self.connections.list_tenant_installations(tenant_id, "slack")
            if context.get("slack_resolution") is not None
            and hasattr(self.connections, "list_tenant_installations")
            else self.connections.list_installations(tenant_id, principal_id)
        )
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
            goal, {**context, "tenant_id": tenant_id}
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
        if not self.slack_writes_enabled:
            raise PermissionError("feature_disabled:slack_writes")
        if capability_id == "slack.direct_message.send" and not self.slack_dms_enabled:
            raise PermissionError("feature_disabled:slack_dms")
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
        if not self.slack_writes_enabled:
            raise PermissionError("feature_disabled:slack_writes")
        if capability_id == "slack.direct_message.send" and not self.slack_dms_enabled:
            raise PermissionError("feature_disabled:slack_dms")
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
