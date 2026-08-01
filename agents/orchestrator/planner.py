"""Capability-grounded dynamic planning and deterministic compilation."""

import hashlib
import json
import unicodedata
from collections import defaultdict

import jsonschema
from pydantic import ValidationError

from agents.orchestrator.workflow_models import WorkflowPlanDraft
from agents.orchestrator.slack_conversation import interpret_slack_turn
from libs.integrations.catalog import (
    ConnectionCapabilitySnapshot,
    TrustedCapabilityDefinition,
)


class PlanRejected(ValueError):
    pass


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _hash(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _definition_projection(definition):
    return {
        "capability_id": definition.capability_id,
        "version": definition.version,
        "provider": definition.provider,
        "input_schema": definition.input_schema,
        "output_schema": definition.output_schema,
        "required_scopes": sorted(definition.required_scopes),
        "effect": definition.effect,
        "risk": definition.risk,
        "retry_policy": definition.retry_policy,
        "preview_fields": list(definition.preview_fields),
        "verifier": definition.verifier,
    }


def descriptor_hash(definition):
    return _hash(_definition_projection(definition))


class PlanCompiler(object):
    MAX_STEPS = 10

    def __init__(self, definitions, snapshots, rollout_version):
        self.definitions = {
            (item.capability_id, item.version): item
            for item in definitions
            if isinstance(item, TrustedCapabilityDefinition)
        }
        self.snapshots = {
            (item.capability_id, item.capability_version, item.connection_id): item
            for item in snapshots
            if isinstance(item, ConnectionCapabilitySnapshot)
        }
        self.rollout_version = rollout_version

    def capability_projection(self):
        projections = []
        for item in self.definitions.values():
            projection = _definition_projection(item)
            projection["connections"] = sorted({
                snapshot.connection_id
                for snapshot in self.snapshots.values()
                if snapshot.capability_id == item.capability_id
                and snapshot.capability_version == item.version
                and snapshot.health == "healthy"
                and snapshot.rollout_version == self.rollout_version
                and item.required_scopes.issubset(snapshot.effective_scopes)
            })
            projection["descriptor_snapshot_hash"] = descriptor_hash(item)
            projections.append(projection)
        return sorted(
            projections,
            key=lambda item: (item["capability_id"], item["version"]),
        )

    def compile(self, raw_plan):
        try:
            draft = WorkflowPlanDraft.model_validate(raw_plan)
        except ValidationError as exc:
            raise PlanRejected("plan shape is invalid") from exc
        if not draft.tenant_id:
            raise PlanRejected("tenant binding is required")
        if not draft.steps:
            raise PlanRejected("plan has no steps")
        if len(draft.steps) > self.MAX_STEPS:
            raise PlanRejected("plan exceeds the ten steps limit")
        by_id = {}
        validated = []
        disclosures = []
        for step in draft.steps:
            if step.step_id in by_id:
                raise PlanRejected("step identifiers must be unique")
            by_id[step.step_id] = step
            definition = self.definitions.get(
                (step.capability_id, step.capability_version)
            )
            if definition is None:
                raise PlanRejected("capability is not catalogued")
            if step.descriptor_snapshot_hash != descriptor_hash(definition):
                raise PlanRejected("descriptor snapshot is stale")
            snapshot = self.snapshots.get(
                (step.capability_id, step.capability_version, step.connection_id)
            )
            if snapshot is None or snapshot.tenant_id != draft.tenant_id:
                raise PlanRejected("connection is not authorized for this tenant")
            if (
                snapshot.health != "healthy"
                or snapshot.rollout_version != self.rollout_version
                or not definition.required_scopes.issubset(snapshot.effective_scopes)
            ):
                raise PlanRejected("connection capability snapshot is stale")
            safe_input, step_disclosures = self._authorize_data_flow(
                step.input, definition.provider, step.step_id
            )
            disclosures.extend(step_disclosures)
            try:
                jsonschema.validate(
                    safe_input, _allow_declared_references(definition.input_schema)
                )
            except jsonschema.ValidationError as exc:
                raise PlanRejected(
                    "input schema rejected step %s" % step.step_id
                ) from exc
            validated.append({
                "step_id": step.step_id,
                "capability_id": step.capability_id,
                "capability_version": step.capability_version,
                "connection_id": step.connection_id,
                "descriptor_snapshot_hash": step.descriptor_snapshot_hash,
                "credential_version": snapshot.credential_version,
                "input": safe_input,
                "depends_on": sorted(set(step.depends_on)),
                "effect": definition.effect,
                "risk": definition.risk,
                "retry_policy": definition.retry_policy,
                "provider": definition.provider,
                "agent_offer_id": step.agent_offer_id,
            })
        order = self._topological_order(validated)
        ordered = [next(item for item in validated if item["step_id"] == step_id)
                   for step_id in order]
        self._validate_references(ordered)
        disclosures.extend(self._reference_disclosures(ordered))
        graph_material = {
            "tenant_id": draft.tenant_id,
            "goal": draft.goal,
            "steps": ordered,
        }
        return {
            **graph_material,
            "steps": ordered,
            "plan_graph_hash": _hash(graph_material),
            "capability_snapshot_hash": _hash([
                {
                    "connection_id": item["connection_id"],
                    "capability_id": item["capability_id"],
                    "capability_version": item["capability_version"],
                    "descriptor_snapshot_hash": item["descriptor_snapshot_hash"],
                    "credential_version": item["credential_version"],
                } for item in ordered
            ]),
            "disclosures": disclosures,
            "blockers": list(draft.blockers),
        }

    def _topological_order(self, steps):
        ids = {item["step_id"] for item in steps}
        indegree = {item["step_id"]: 0 for item in steps}
        outgoing = defaultdict(list)
        for item in steps:
            for dependency in item["depends_on"]:
                if dependency not in ids or dependency == item["step_id"]:
                    raise PlanRejected("dependency is unknown or self-referential")
                indegree[item["step_id"]] += 1
                outgoing[dependency].append(item["step_id"])
        ready = sorted(step_id for step_id, count in indegree.items() if count == 0)
        order = []
        while ready:
            step_id = ready.pop(0)
            order.append(step_id)
            for child in sorted(outgoing[step_id]):
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
                    ready.sort()
        if len(order) != len(steps):
            raise PlanRejected("plan dependency graph is cyclic")
        return order

    def _validate_references(self, steps):
        by_id = {item["step_id"]: item for item in steps}
        for step in steps:
            ancestors = self._ancestors(step, by_id)
            for path, reference in _references_with_paths(step["input"]):
                pieces = reference.split(".")
                if len(pieces) < 3 or pieces[0] not in ancestors or pieces[1] not in ("output", "receipt"):
                    raise PlanRejected("output reference is invalid")
                source = by_id[pieces[0]]
                recipient_fields = {"to", "recipient", "recipients", "attendee", "attendees"}
                if step["provider"] == "google" and recipient_fields.intersection(
                    str(part).lower() for part in path
                ):
                    raise PlanRejected(
                        "dynamic identities require an explicit confirmed recipient"
                    )
                source_definition = self.definitions[
                    (source["capability_id"], source["capability_version"])
                ]
                destination_definition = self.definitions[
                    (step["capability_id"], step["capability_version"])
                ]
                source_schemas = _schemas_at_path(
                    source_definition.output_schema, pieces[2:]
                )
                if not source_schemas:
                    raise PlanRejected("undeclared source output path")
                destination_schemas = _schemas_at_path(
                    destination_definition.input_schema, path,
                    allow_array_indices=True,
                )
                if not destination_schemas:
                    raise PlanRejected("undeclared destination input path")
                if not _schemas_are_compatible(
                    source_schemas, destination_schemas
                ):
                    raise PlanRejected("incompatible reference type")

    @staticmethod
    def _reference_disclosures(steps):
        by_id = {item["step_id"]: item for item in steps}
        disclosures = []
        for step in steps:
            for reference in _references(step["input"]):
                source_step = by_id[reference.split(".", 1)[0]]
                if source_step["provider"] == step["provider"]:
                    continue
                if source_step.get("agent_offer_id") or step.get("agent_offer_id"):
                    raise PlanRejected(
                        "provider-to-agent data flow requires an explicit trusted policy"
                    )
                disclosures.append({
                    "step_id": step["step_id"],
                    "source_step_id": source_step["step_id"],
                    "source": source_step["provider"],
                    "destination": step["provider"],
                    "classification": "provider_data",
                    "reference": reference,
                })
        return disclosures

    @staticmethod
    def _ancestors(step, by_id):
        result = set()
        pending = list(step["depends_on"])
        while pending:
            item = pending.pop()
            if item in result:
                continue
            result.add(item)
            pending.extend(by_id[item]["depends_on"])
        return result

    def _authorize_data_flow(self, value, destination_provider, step_id):
        disclosures = []
        if isinstance(value, dict):
            if set(value) == {"$value", "$provenance"}:
                provenance = value["$provenance"]
                if not isinstance(provenance, dict):
                    raise PlanRejected("data provenance is malformed")
                source = provenance.get("provider")
                allowed = provenance.get("allowed_destinations", [])
                if source != destination_provider and destination_provider not in allowed:
                    raise PlanRejected("data flow is not authorized")
                disclosures.append({
                    "step_id": step_id,
                    "source": source,
                    "destination": destination_provider,
                    "classification": provenance.get("classification", "unknown"),
                })
                return value["$value"], disclosures
            result = {}
            for key, item in value.items():
                clean, nested = self._authorize_data_flow(
                    item, destination_provider, step_id
                )
                result[key] = clean
                disclosures.extend(nested)
            return result, disclosures
        if isinstance(value, list):
            result = []
            for item in value:
                clean, nested = self._authorize_data_flow(
                    item, destination_provider, step_id
                )
                result.append(clean)
                disclosures.extend(nested)
            return result, disclosures
        return value, disclosures


class DynamicPlanner(object):
    def __init__(self, model, compiler, shadow_mode=True):
        self.model = model
        self.compiler = compiler
        self.shadow_mode = bool(shadow_mode)

    def plan(self, goal, context=None):
        context = dict(context or {})
        capabilities = self.compiler.capability_projection()
        generate_plan = getattr(self.model, "generate_plan", None)
        if callable(generate_plan):
            raw_plan = generate_plan(goal, capabilities, context)
        else:
            raw_plan = _offline_public_slack_plan(goal, capabilities, context)
        _ground_slack_entity_ids(raw_plan, context)
        compiled = self.compiler.compile(raw_plan)
        compiled["shadow_mode"] = self.shadow_mode
        return compiled


def _offline_public_slack_plan(goal, capabilities, context):
    normalized = unicodedata.normalize("NFKD", str(goal).lower())
    normalized = "".join(character for character in normalized
                         if not unicodedata.combining(character))
    resolution = dict(context.get("slack_resolution") or {})
    turn = interpret_slack_turn(goal, resolution)
    is_public_channel_list = (
        "slack" in normalized and ("canal" in normalized or "channel" in normalized)
        and "public" in normalized
        and any(word in normalized for word in ("lista", "listar", "muestra", "show", "list"))
    )
    is_private_channel_list = (
        "slack" in normalized and ("canal" in normalized or "channel" in normalized)
        and ("privad" in normalized or "private" in normalized)
        and any(word in normalized for word in ("lista", "listar", "muestra", "show", "list"))
    )
    operation = ("private_channels" if is_private_channel_list else
                 "channels" if is_public_channel_list else turn.operation)
    capability_ids = {
        "channels": "slack.channels.list",
        "private_channels": "slack.private_channels.list",
        "read": "slack.conversation.read",
        "summarize": "slack.conversation.read",
        "post": "slack.message.send",
        "reply": "slack.thread.reply",
        "dm": "slack.direct_message.send",
    }
    wanted = capability_ids.get(operation)
    candidates = [item for item in capabilities
                  if item["capability_id"] == wanted and item.get("connections")]
    tenant_id = context.get("tenant_id")
    connection = (resolution.get("active_connection") or {}).get("id")
    capability = next((item for item in candidates
                       if connection in item["connections"]), None) if connection else None
    if capability is None and len(candidates) == 1 and len(candidates[0]["connections"]) == 1:
        capability = candidates[0]
        connection = capability["connections"][0]
    if capability is None or not tenant_id:
        raise PlanRejected("planning model cannot generate this workflow")
    payload = {}
    channel = (resolution.get("active_channel") or {}).get("id")
    person = (resolution.get("active_person") or {}).get("id")
    thread = resolution.get("active_thread") or {}
    message = resolution.get("message_text") or turn.message_text
    if operation in ("read", "summarize", "post", "reply"):
        if not channel:
            raise PlanRejected("Slack channel must be resolved before planning")
        payload["channel_id"] = channel
    if operation == "reply":
        if not thread.get("thread_ts"):
            raise PlanRejected("Slack thread must be resolved before planning")
        payload["thread_ts"] = thread["thread_ts"]
    if operation == "dm":
        if not person:
            raise PlanRejected("Slack person must be resolved before planning")
        payload["user_id"] = person
    if operation in ("post", "reply", "dm"):
        if not message:
            raise PlanRejected("Slack message text is required before planning")
        payload["text"] = message
    return {
        "tenant_id": tenant_id,
        "goal": goal,
        "steps": [{
            "step_id": "slack-public-channels",
            "capability_id": capability["capability_id"],
            "capability_version": capability["version"],
            "connection_id": connection,
            "descriptor_snapshot_hash": capability["descriptor_snapshot_hash"],
            "input": payload,
            "depends_on": [],
        }],
    }


def _ground_slack_entity_ids(raw_plan, context):
    """A model can name an operation, never mint provider entity authority."""
    if hasattr(raw_plan, "model_dump"):
        material = raw_plan.model_dump()
    else:
        material = raw_plan
    resolution = dict((context or {}).get("slack_resolution") or {})
    trusted = {
        "channel_id": (resolution.get("active_channel") or {}).get("id"),
        "user_id": (resolution.get("active_person") or {}).get("id"),
        "thread_ts": (resolution.get("active_thread") or {}).get("thread_ts"),
    }
    for step in material.get("steps", []) if isinstance(material, dict) else []:
        if not str(step.get("capability_id", "")).startswith("slack."):
            continue
        payload = step.get("input") if isinstance(step.get("input"), dict) else {}
        for field, expected in trusted.items():
            if field in payload and (expected is None or payload[field] != expected):
                raise PlanRejected("Slack entity is not deterministically resolved")


def _references(value):
    found = []
    if isinstance(value, dict):
        if set(value) == {"$ref"} and isinstance(value["$ref"], str):
            found.append(value["$ref"])
        else:
            for item in value.values():
                found.extend(_references(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_references(item))
    return found


def _references_with_paths(value, path=()):
    found = []
    if isinstance(value, dict):
        if set(value) == {"$ref"} and isinstance(value["$ref"], str):
            found.append((path, value["$ref"]))
        else:
            for key, item in value.items():
                found.extend(_references_with_paths(item, path + (str(key),)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_references_with_paths(item, path + (str(index),)))
    return found


def _schemas_at_path(schema, path, allow_array_indices=False):
    candidates = _schema_alternatives(schema)
    for part in path:
        next_candidates = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            properties = candidate.get("properties")
            if isinstance(properties, dict) and part in properties:
                next_candidates.extend(_schema_alternatives(properties[part]))
                continue
            if (
                allow_array_indices
                and _schema_allows_type(candidate, "array")
                and str(part).isdigit()
            ):
                items = candidate.get("items")
                if isinstance(items, dict):
                    next_candidates.extend(_schema_alternatives(items))
        candidates = next_candidates
        if not candidates:
            break
    return candidates


def _schema_alternatives(schema):
    if not isinstance(schema, dict):
        return []
    alternatives = [schema]
    for keyword in ("oneOf", "anyOf", "allOf"):
        values = schema.get(keyword)
        if isinstance(values, list):
            for value in values:
                alternatives.extend(_schema_alternatives(value))
    return alternatives


def _schemas_are_compatible(source_schemas, destination_schemas):
    source_types = set().union(*(
        _schema_types(schema) for schema in source_schemas
    ))
    destination_types = set().union(*(
        _schema_types(schema) for schema in destination_schemas
    ))
    if not source_types or not destination_types:
        return False
    compatible_destination_types = set(destination_types)
    if "number" in destination_types:
        compatible_destination_types.add("integer")
    return source_types.issubset(compatible_destination_types)


def _schema_allows_type(schema, expected):
    types = _schema_types(schema)
    return expected in types or (expected == "integer" and "number" in types)


def _schema_types(schema):
    if not isinstance(schema, dict):
        return set()
    declared = schema.get("type")
    if isinstance(declared, str):
        types = {declared}
    elif isinstance(declared, list):
        types = {item for item in declared if isinstance(item, str)}
    elif "properties" in schema:
        types = {"object"}
    elif "items" in schema:
        types = {"array"}
    elif "const" in schema:
        types = {_json_type(schema["const"])}
    elif isinstance(schema.get("enum"), list):
        types = {_json_type(item) for item in schema["enum"]}
    else:
        types = set()
    alternatives = set()
    for keyword in ("oneOf", "anyOf"):
        values = schema.get(keyword)
        if isinstance(values, list):
            for item in values:
                alternatives.update(_schema_types(item))
    if alternatives:
        types = types.intersection(alternatives) if types else alternatives
    all_of = schema.get("allOf")
    if isinstance(all_of, list) and all_of:
        all_types = [_schema_types(item) for item in all_of]
        constrained_types = [item for item in all_types if item]
        constrained = (
            set.intersection(*constrained_types) if constrained_types else set()
        )
        types = (
            types.intersection(constrained)
            if types and constrained else constrained or types
        )
    return types


def _json_type(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _allow_declared_references(schema, allow_self=False):
    """Permit a typed field to be supplied by an approved dependency reference."""
    reference = {
        "type": "object", "required": ["$ref"],
        "properties": {"$ref": {"type": "string"}},
        "additionalProperties": False,
    }
    if not isinstance(schema, dict):
        return schema
    transformed = {}
    for key, value in schema.items():
        if key == "properties" and isinstance(value, dict):
            transformed[key] = {
                name: _allow_declared_references(child, allow_self=True)
                for name, child in value.items()
            }
        elif key == "items":
            transformed[key] = _allow_declared_references(value, allow_self=True)
        elif key in ("oneOf", "anyOf", "allOf") and isinstance(value, list):
            transformed[key] = [
                _allow_declared_references(item, allow_self=allow_self)
                for item in value
            ]
        else:
            transformed[key] = value
    return {"anyOf": [transformed, reference]} if allow_self else transformed
