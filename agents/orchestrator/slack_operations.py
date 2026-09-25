"""Versioned conversational operations joined to trusted capabilities.

The JSON-compatible YAML manifest describes language and product behavior. It
never defines executable authority: schemas, scopes, effects, risk, retry,
verification, and rollout remain properties of ``TrustedCapabilityDefinition``.

The registry is provider-parameterised. Slack was the first provider through
it, so the names read Slack-first; a second provider registers a manifest spec
and joins the same catalog rather than copying this join.
"""

import json
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping, Tuple

from libs.integrations.catalog import (
    AUTHORITY_PROFILES,
    TrustedCapabilityDefinition,
    provider_registration,
)


#: Read from the provider registration rather than restated here: a second copy
#: of a version string is a second thing to forget to bump.
MANIFEST_VERSION = provider_registration("slack").manifest_version
DEFAULT_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "slack_operations_v1.yaml"
)
CONTACTS_MANIFEST_VERSION = provider_registration("contacts").manifest_version
CONTACTS_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2] / "config"
    / "contacts_operations_v1.yaml"
)
TWILIO_MANIFEST_VERSION = provider_registration("twilio").manifest_version
TWILIO_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "twilio_operations_v1.yaml"
)

#: Profiles a manifest may name. Drawn from the catalog rather than restated,
#: so a profile the catalog has stopped honouring cannot survive in a manifest,
#: plus ``none`` for a local operation that executes nothing at all.
MANIFEST_AUTHORITY_PROFILES = frozenset(AUTHORITY_PROFILES) | {"none"}

_TRUSTED_ONLY_FIELDS = frozenset({
    "input_schema", "output_schema", "required_scopes", "effect", "risk",
    "retry_policy", "verifier", "rollout_version",
})
_OPERATION_FIELDS = frozenset({
    "operation_id", "operation_kind", "availability", "aliases", "slots",
    "capability_recipe", "authority_profile", "family_flag", "prerequisites",
    "recovery", "presentation",
})
_RECIPE_FIELDS = frozenset({
    "step_id", "capability_id", "capability_version", "input_bindings",
    "depends_on",
})


class OperationManifestError(ValueError):
    """The operation manifest cannot safely join the trusted catalog."""


#: Retained name: Slack was the first provider through this registry, and
#: existing importers raise and catch it by that name.
SlackOperationManifestError = OperationManifestError


@dataclass(frozen=True)
class OperationManifestSpec:
    """Which manifest belongs to which provider, at which version.

    A provider is added by declaring one of these, not by editing the join.
    """

    provider: str
    manifest_version: str
    manifest_path: Path

    def __post_init__(self):
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise OperationManifestError("manifest provider is required")
        if not isinstance(self.manifest_version, str) or not self.manifest_version:
            raise OperationManifestError("manifest version is required")
        # A manifest version names its provider, so one provider's manifest can
        # never be loaded as another's by version alone.
        if not self.manifest_version.startswith("%s." % self.provider):
            raise OperationManifestError(
                "manifest version must be namespaced by its provider"
            )


@dataclass(frozen=True)
class SlotDescriptor:
    name: str
    entity_kind: str
    required: bool


@dataclass(frozen=True)
class CapabilityRecipeStep:
    step_id: str
    capability_id: str
    capability_version: str
    input_bindings: Mapping[str, str]
    depends_on: Tuple[str, ...]


@dataclass(frozen=True)
class OperationDescriptor:
    operation_id: str
    operation_kind: str
    availability: str
    aliases: Tuple[str, ...]
    slots: Tuple[SlotDescriptor, ...]
    capability_recipe: Tuple[CapabilityRecipeStep, ...]
    authority_profile: str
    family_flag: str
    prerequisites: Tuple[str, ...]
    recovery: Mapping[str, str]
    presentation: Mapping[str, str]


@dataclass(frozen=True)
class ResolvedOperation:
    """Internal operation binding; never accept one from a model or client."""

    descriptor: OperationDescriptor
    trusted_capabilities: Tuple[TrustedCapabilityDefinition, ...]


#: Retained names for existing Slack importers.
SlackSlotDescriptor = SlotDescriptor
SlackCapabilityRecipeStep = CapabilityRecipeStep
SlackOperationDescriptor = OperationDescriptor
ResolvedSlackOperation = ResolvedOperation


class OperationRegistry:
    def __init__(
        self, provider, manifest_version, operations, method_coverage, definitions,
    ):
        if not isinstance(provider, str) or not provider.strip():
            raise OperationManifestError("manifest provider is required")
        if not isinstance(manifest_version, str) or not manifest_version.startswith(
            "%s." % provider
        ):
            raise OperationManifestError(
                "unsupported operation manifest version"
            )
        self.provider = provider
        self.manifest_version = manifest_version
        self.operations = tuple(operations)
        self.method_coverage = method_coverage
        self._definitions = _trusted_definition_index(definitions)
        self._operation_index = {}
        self._alias_index = {}
        aliases = set()
        for operation in self.operations:
            if operation.operation_id in self._operation_index:
                raise SlackOperationManifestError("duplicate operation_id")
            self._operation_index[operation.operation_id] = operation
            for alias in operation.aliases:
                normalized = " ".join(alias.casefold().split())
                if normalized in aliases:
                    raise SlackOperationManifestError("duplicate operation alias")
                aliases.add(normalized)
                self._alias_index[_normalize_alias(alias)] = operation
            self._validate_trusted_join(operation)

    @property
    def family_flags(self):
        return frozenset(operation.family_flag for operation in self.operations)

    def get(self, operation_id):
        return self._operation_index.get(operation_id)

    def scope_bundles(self, definitions):
        """Group install scopes by the family that needs them.

        Asking for every scope at install trains people to approve without
        reading. A bundle is the smallest grant that makes one family work,
        named by the family so the request can say what it buys.
        """
        scopes_by_capability = {
            definition.capability_id: frozenset(definition.required_scopes)
            for definition in definitions
        }
        bundles = {}
        for operation in self.operations:
            capabilities = {
                step.capability_id for step in operation.capability_recipe
            }
            known = capabilities & set(scopes_by_capability)
            if not known:
                continue
            bundle = bundles.setdefault(operation.family_flag, {
                "family": operation.family_flag,
                "capabilities": set(), "scopes": set(), "operations": set(),
            })
            bundle["capabilities"] |= known
            bundle["operations"].add(operation.operation_id)
            for capability_id in known:
                bundle["scopes"] |= scopes_by_capability[capability_id]
        return {
            family: {
                "family": family,
                "capabilities": sorted(bundle["capabilities"]),
                "operations": sorted(bundle["operations"]),
                "scopes": sorted(bundle["scopes"]),
            }
            for family, bundle in bundles.items()
        }

    def missing_scope_bundles(self, definitions, granted_scopes, families=None):
        """Return only the families a connection cannot yet run, and why."""
        granted = frozenset(granted_scopes or ())
        bundles = self.scope_bundles(definitions)
        wanted = set(families) if families else set(bundles)
        missing = []
        for family in sorted(wanted & set(bundles)):
            bundle = bundles[family]
            absent = sorted(set(bundle["scopes"]) - granted)
            if absent:
                missing.append(dict(bundle, missing_scopes=absent))
        return missing

    def lookup_alias(self, text):
        """Find one manifest operation from deterministic human-language aliases."""
        normalized = _normalize_alias(text)
        matches = [
            (len(alias), operation)
            for alias, operation in self._alias_index.items()
            if alias and alias in normalized
        ]
        if not matches:
            return None
        matches.sort(key=lambda item: (-item[0], item[1].operation_id))
        return matches[0][1]

    def resolve_visible(
        self, installed_capability_ids, family_flags, policy_visible=None,
    ):
        installed = _string_set(
            installed_capability_ids, "installed capability ids"
        )
        unknown = installed - {
            definition.capability_id for definition in self._definitions.values()
        }
        if unknown:
            raise SlackOperationManifestError(
                "installed capability is not present in the trusted catalog"
            )
        if not isinstance(family_flags, Mapping):
            raise SlackOperationManifestError("family flags must be a mapping")
        if policy_visible is not None and not callable(policy_visible):
            raise SlackOperationManifestError("policy visibility must be callable")

        visible = []
        for operation in self.operations:
            required = {
                step.capability_id for step in operation.capability_recipe
            }
            if not required.issubset(installed):
                continue
            if family_flags.get(operation.family_flag) is not True:
                continue
            if policy_visible is not None:
                try:
                    permitted = policy_visible(operation) is True
                except Exception:
                    permitted = False
                if not permitted:
                    continue
            definitions = tuple(
                self._definitions[(step.capability_id, step.capability_version)]
                for step in operation.capability_recipe
            )
            visible.append(ResolvedOperation(operation, definitions))
        return tuple(visible)

    def model_projection(
        self, installed_capability_ids, family_flags, policy_visible=None,
    ):
        """Return language metadata only, with no executable capability data."""
        return tuple(
            {
                "operation_id": resolved.descriptor.operation_id,
                "operation_kind": resolved.descriptor.operation_kind,
                "availability": resolved.descriptor.availability,
                "aliases": list(resolved.descriptor.aliases),
                "slots": [
                    {
                        "name": slot.name,
                        "entity_kind": slot.entity_kind,
                        "required": slot.required,
                    }
                    for slot in resolved.descriptor.slots
                ],
                "prerequisites": list(resolved.descriptor.prerequisites),
                "recovery": dict(resolved.descriptor.recovery),
                "presentation": dict(resolved.descriptor.presentation),
            }
            for resolved in self.resolve_visible(
                installed_capability_ids, family_flags, policy_visible,
            )
        )

    def _validate_trusted_join(self, operation):
        if operation.operation_kind == "local":
            if operation.capability_recipe or operation.authority_profile != "none":
                raise SlackOperationManifestError(
                    "local operations may not declare executable authority"
                )
            return
        if not operation.capability_recipe:
            raise SlackOperationManifestError(
                "capability operations require a runtime recipe"
            )
        if operation.authority_profile == "none":
            raise SlackOperationManifestError(
                "capability operations require an authority profile"
            )
        slot_names = {slot.name for slot in operation.slots}
        step_ids = {step.step_id for step in operation.capability_recipe}
        for step in operation.capability_recipe:
            key = (step.capability_id, step.capability_version)
            definition = self._definitions.get(key)
            if definition is None:
                raise SlackOperationManifestError(
                    "operation capability version is not trusted"
                )
            if definition.provider != self.provider:
                raise SlackOperationManifestError(
                    "operation capability provider is incompatible"
                )
            schema = definition.input_schema
            properties = schema.get("properties") if isinstance(schema, Mapping) else None
            required = schema.get("required", ()) if isinstance(schema, Mapping) else ()
            if (
                not isinstance(schema, Mapping)
                or schema.get("type") != "object"
                or not isinstance(properties, Mapping)
            ):
                raise SlackOperationManifestError(
                    "trusted capability input schema is incompatible"
                )
            bound_inputs = set(step.input_bindings)
            unknown_inputs = bound_inputs - set(properties)
            if unknown_inputs:
                raise SlackOperationManifestError(
                    "recipe input is absent from trusted capability schema"
                )
            missing_required = set(required) - bound_inputs
            if missing_required:
                raise SlackOperationManifestError(
                    "recipe omits a trusted required input"
                )
            for source in step.input_bindings.values():
                if source.split(".", 1)[0] not in slot_names:
                    raise SlackOperationManifestError(
                        "recipe input references an undeclared slot"
                    )
            if not set(step.depends_on).issubset(step_ids - {step.step_id}):
                raise SlackOperationManifestError(
                    "recipe dependency references an unknown step"
                )


#: Retained name for existing Slack importers.
SlackOperationRegistry = OperationRegistry


SLACK_MANIFEST = OperationManifestSpec(
    provider="slack",
    manifest_version=MANIFEST_VERSION,
    manifest_path=DEFAULT_MANIFEST_PATH,
)


def load_operations(spec, definitions):
    """Join one provider's manifest to the trusted catalog, fail-closed.

    The manifest supplies language and presentation. Every executable
    property — schema, scope, effect, risk, retry, verifier — comes from the
    definitions, and a manifest that tries to declare one is refused.
    """
    if not isinstance(spec, OperationManifestSpec):
        raise SlackOperationManifestError("an operation manifest spec is required")
    try:
        payload = json.loads(Path(spec.manifest_path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise SlackOperationManifestError(
            "operation manifest is unreadable"
        ) from exc
    if not isinstance(payload, Mapping):
        raise SlackOperationManifestError("operation manifest must be an object")
    if set(payload) != {"manifest_version", "provider", "operations", "method_coverage"}:
        raise SlackOperationManifestError("operation manifest fields are invalid")
    if payload.get("manifest_version") != spec.manifest_version:
        raise SlackOperationManifestError(
            "unsupported operation manifest version"
        )
    if payload.get("provider") != spec.provider:
        raise SlackOperationManifestError("operation manifest provider is invalid")
    operations = payload.get("operations")
    if not isinstance(operations, list) or not operations:
        raise SlackOperationManifestError("manifest operations must be a non-empty list")
    parsed = tuple(_parse_operation(item, spec.provider) for item in operations)
    coverage = _parse_method_coverage(payload.get("method_coverage"))
    return OperationRegistry(
        spec.provider, payload["manifest_version"], parsed, coverage, definitions,
    )


def load_slack_operations(definitions, manifest_path=DEFAULT_MANIFEST_PATH):
    """Slack's manifest, loaded through the provider-neutral path."""
    return load_operations(
        replace(SLACK_MANIFEST, manifest_path=Path(manifest_path)), definitions,
    )


CONTACTS_MANIFEST = OperationManifestSpec(
    provider="contacts",
    manifest_version=CONTACTS_MANIFEST_VERSION,
    manifest_path=CONTACTS_MANIFEST_PATH,
)

TWILIO_MANIFEST = OperationManifestSpec(
    provider="twilio", manifest_version=TWILIO_MANIFEST_VERSION,
    manifest_path=TWILIO_MANIFEST_PATH,
)


def load_twilio_operations(definitions, manifest_path=TWILIO_MANIFEST_PATH):
    return load_operations(
        replace(TWILIO_MANIFEST, manifest_path=Path(manifest_path)), definitions,
    )


def load_contacts_operations(
    definitions, manifest_path=CONTACTS_MANIFEST_PATH,
):
    """The contacts manifest, through the same join Slack uses.

    Same function, same fail-closed checks, same refusal to let a manifest
    declare authority. A first-party store gets no shortcut here: its
    operations are trusted because the catalog says so, not because the store
    happens to be ours.
    """
    return load_operations(
        replace(CONTACTS_MANIFEST, manifest_path=Path(manifest_path)),
        definitions,
    )


def _parse_operation(value, provider):
    if not isinstance(value, Mapping):
        raise SlackOperationManifestError("manifest operation fields are invalid")
    forbidden = set(value) & _TRUSTED_ONLY_FIELDS
    if forbidden:
        raise SlackOperationManifestError(
            "manifest may not define trusted capability authority"
        )
    if set(value) != _OPERATION_FIELDS:
        raise SlackOperationManifestError("manifest operation fields are invalid")
    operation_id = _required_string(value.get("operation_id"), "operation_id")
    if not operation_id.startswith("%s." % provider):
        raise SlackOperationManifestError(
            "operation_id must be namespaced by its provider"
        )
    availability = value.get("availability")
    if availability not in {"supported", "conditional"}:
        raise SlackOperationManifestError("operation availability is invalid")
    aliases = _string_tuple(value.get("aliases"), "operation aliases")
    slots_value = value.get("slots")
    if not isinstance(slots_value, list):
        raise SlackOperationManifestError("operation slots must be a list")
    slots = tuple(_parse_slot(slot) for slot in slots_value)
    if len({slot.name for slot in slots}) != len(slots):
        raise SlackOperationManifestError("operation slot names must be unique")
    operation_kind = value.get("operation_kind")
    if operation_kind not in {"capability", "local"}:
        raise SlackOperationManifestError("operation kind is invalid")
    recipe_value = value.get("capability_recipe")
    if not isinstance(recipe_value, list):
        raise SlackOperationManifestError("capability recipe must be a list")
    recipe = tuple(_parse_recipe_step(step) for step in recipe_value)
    if len({step.step_id for step in recipe}) != len(recipe):
        raise SlackOperationManifestError("recipe step ids must be unique")
    authority_profile = value.get("authority_profile")
    if authority_profile not in MANIFEST_AUTHORITY_PROFILES:
        raise SlackOperationManifestError("authority profile is invalid")
    family_flag = _required_string(value.get("family_flag"), "family flag")
    prerequisites = _string_tuple(value.get("prerequisites"), "prerequisites")
    recovery = _string_mapping(value.get("recovery"), "recovery")
    presentation = _string_mapping(value.get("presentation"), "presentation")
    return OperationDescriptor(
        operation_id=operation_id,
        operation_kind=operation_kind,
        availability=availability,
        aliases=aliases,
        slots=slots,
        capability_recipe=recipe,
        authority_profile=authority_profile,
        family_flag=family_flag,
        prerequisites=prerequisites,
        recovery=recovery,
        presentation=presentation,
    )


def _parse_slot(value):
    if not isinstance(value, Mapping) or set(value) != {
        "name", "entity_kind", "required",
    }:
        raise SlackOperationManifestError("operation slot fields are invalid")
    name = _required_string(value.get("name"), "slot name")
    entity_kind = _required_string(value.get("entity_kind"), "entity kind")
    if "." not in entity_kind:
        raise SlackOperationManifestError("entity kind must be namespaced")
    if not isinstance(value.get("required"), bool):
        raise SlackOperationManifestError("slot required must be boolean")
    return SlotDescriptor(name, entity_kind, value["required"])


def _parse_recipe_step(value):
    if not isinstance(value, Mapping) or set(value) != _RECIPE_FIELDS:
        raise SlackOperationManifestError("capability recipe fields are invalid")
    bindings = value.get("input_bindings")
    if not isinstance(bindings, Mapping) or any(
        not isinstance(key, str) or not key or not isinstance(source, str) or not source
        for key, source in bindings.items()
    ):
        raise SlackOperationManifestError("recipe input bindings are invalid")
    return CapabilityRecipeStep(
        step_id=_required_string(value.get("step_id"), "recipe step id"),
        capability_id=_required_string(
            value.get("capability_id"), "recipe capability id"
        ),
        capability_version=_required_string(
            value.get("capability_version"), "recipe capability version"
        ),
        input_bindings=dict(bindings),
        depends_on=_string_tuple(value.get("depends_on"), "recipe dependencies", empty=True),
    )


def _parse_method_coverage(value):
    if not isinstance(value, Mapping) or set(value) != {
        "supported", "conditional", "excluded",
    }:
        raise SlackOperationManifestError("method coverage is incomplete")
    result = {}
    methods = set()
    for status in ("supported", "conditional", "excluded"):
        entries = value.get(status)
        if not isinstance(entries, list) or not entries:
            raise SlackOperationManifestError("method coverage lists must be non-empty")
        parsed = []
        for entry in entries:
            expected = {"method", "family", "state", "prerequisites"}
            if status == "excluded":
                expected.add("reason")
            if not isinstance(entry, Mapping) or set(entry) != expected:
                raise SlackOperationManifestError("method coverage entry is invalid")
            method = _required_string(entry.get("method"), "provider method")
            if method in methods:
                raise SlackOperationManifestError(
                    "provider method coverage is duplicated"
                )
            methods.add(method)
            state = entry.get("state")
            valid_states = {
                "supported": {"runtime"},
                "conditional": {"runtime", "planned", "dormant"},
                "excluded": {"dormant"},
            }[status]
            if state not in valid_states:
                raise SlackOperationManifestError(
                    "method coverage lifecycle state is invalid"
                )
            item = {
                "method": method,
                "family": _required_string(entry.get("family"), "method family"),
                "state": state,
                "prerequisites": _string_tuple(
                    entry.get("prerequisites"), "method prerequisites"
                ),
            }
            if status == "excluded":
                item["reason"] = _required_string(entry.get("reason"), "exclusion reason")
            parsed.append(item)
        result[status] = tuple(parsed)
    return result


def _trusted_definition_index(definitions):
    index = {}
    capability_ids = {}
    for definition in definitions:
        if not isinstance(definition, TrustedCapabilityDefinition):
            raise SlackOperationManifestError(
                "operation joins require trusted capability definitions"
            )
        key = (definition.capability_id, definition.version)
        if key in index:
            raise SlackOperationManifestError("trusted capability version is duplicated")
        existing_version = capability_ids.get(definition.capability_id)
        if existing_version is not None and existing_version != definition.version:
            raise SlackOperationManifestError(
                "multiple trusted capability versions require an explicit rollout"
            )
        capability_ids[definition.capability_id] = definition.version
        index[key] = definition
    return index


def _required_string(value, label):
    if not isinstance(value, str) or not value.strip():
        raise SlackOperationManifestError("%s must be a non-empty string" % label)
    return value.strip()


def _string_tuple(value, label, empty=False):
    if not isinstance(value, list) or (not empty and not value):
        raise SlackOperationManifestError("%s must be a string list" % label)
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise SlackOperationManifestError("%s must contain non-empty strings" % label)
    result = tuple(item.strip() for item in value)
    if len(set(result)) != len(result):
        raise SlackOperationManifestError("%s must not contain duplicates" % label)
    return result


def _string_set(value, label):
    if isinstance(value, (str, bytes)):
        raise SlackOperationManifestError("%s must be an iterable" % label)
    try:
        result = set(value)
    except TypeError as exc:
        raise SlackOperationManifestError("%s must be an iterable" % label) from exc
    if any(not isinstance(item, str) or not item for item in result):
        raise SlackOperationManifestError("%s must contain strings" % label)
    return result


def _string_mapping(value, label):
    if not isinstance(value, Mapping) or not value or any(
        not isinstance(key, str) or not key or not isinstance(item, str) or not item
        for key, item in value.items()
    ):
        raise SlackOperationManifestError("%s must be a string mapping" % label)
    return dict(value)


def _normalize_alias(value):
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join("".join(
        char for char in normalized if not unicodedata.combining(char)
    ).casefold().split())
