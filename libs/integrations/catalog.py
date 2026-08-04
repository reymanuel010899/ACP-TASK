"""Authority-separated capability catalog and native provider registry.

Only :class:`TrustedCapabilityDefinition` values can bind executable code.
Connection snapshots are live tenant authority.  External offers are
discovery input only and intentionally cannot enter the runtime registry.
"""

from dataclasses import dataclass
from typing import Any, FrozenSet, Mapping, Optional, Tuple


class CapabilityUnavailable(Exception):
    """A descriptor or live connection snapshot is not executable."""


@dataclass(frozen=True)
class TrustedCapabilityDefinition:
    capability_id: str
    version: str
    provider: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    required_scopes: FrozenSet[str]
    effect: str
    risk: str
    retry_policy: str
    preview_fields: Tuple[str, ...]
    verifier: Optional[str]

    def __post_init__(self):
        if not self.capability_id or "." not in self.capability_id:
            raise ValueError("a namespaced capability_id is required")
        if self.effect not in ("read", "write"):
            raise ValueError("effect must be read or write")
        if self.effect == "write" and not self.preview_fields:
            raise ValueError("write capabilities require preview fields")


@dataclass(frozen=True)
class ConnectionCapabilitySnapshot:
    connection_id: str
    tenant_id: str
    capability_id: str
    capability_version: str
    credential_version: int
    effective_scopes: FrozenSet[str]
    health: str
    rollout_version: str

    @classmethod
    def from_mapping(cls, value):
        if not isinstance(value, Mapping):
            raise CapabilityUnavailable("connection snapshot is required")
        try:
            return cls(
                connection_id=value["connection_id"],
                tenant_id=value["tenant_id"],
                capability_id=value["capability_id"],
                capability_version=value["capability_version"],
                credential_version=int(value["credential_version"]),
                effective_scopes=frozenset(value.get("effective_scopes", ())),
                health=value["health"],
                rollout_version=value["rollout_version"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CapabilityUnavailable("connection snapshot is malformed") from exc


@dataclass(frozen=True)
class ExternalAgentOffer:
    offer_id: str
    agent_principal_id: str
    capability_id: str
    capability_version: str


@dataclass(frozen=True)
class ProviderRuntime:
    provider: str
    connector: Any
    executor: Any
    definitions: Tuple[TrustedCapabilityDefinition, ...]

    def __post_init__(self):
        if not self.provider or self.connector is None or self.executor is None:
            raise ValueError("provider, connector and executor are required")
        for definition in self.definitions:
            if not isinstance(definition, TrustedCapabilityDefinition):
                raise TypeError("runtime definitions must be trusted")
            if definition.provider != self.provider:
                raise ValueError("definition provider does not match runtime")


@dataclass(frozen=True)
class CapabilityBinding:
    definition: TrustedCapabilityDefinition
    connector: Any
    executor: Any
    snapshot: ConnectionCapabilitySnapshot


class ProviderRuntimeRegistry:
    def __init__(self, runtimes=()):
        self._definitions = {}
        for runtime in runtimes:
            self.register(runtime)

    def register(self, runtime):
        if not isinstance(runtime, ProviderRuntime):
            raise TypeError("only trusted provider runtimes can be registered")
        for definition in runtime.definitions:
            key = (definition.capability_id, definition.version)
            if key in self._definitions:
                raise ValueError("duplicate trusted capability version")
            self._definitions[key] = (definition, runtime)

    def definitions(self):
        return tuple(
            definition
            for definition, _runtime in self._definitions.values()
        )

    def resolve(self, snapshot, expected_rollout):
        if not isinstance(snapshot, ConnectionCapabilitySnapshot):
            raise TypeError("a trusted connection snapshot is required")
        entry = self._definitions.get(
            (snapshot.capability_id, snapshot.capability_version)
        )
        if entry is None:
            raise CapabilityUnavailable("capability version is not registered")
        definition, runtime = entry
        if snapshot.health != "healthy":
            raise CapabilityUnavailable("connection is not healthy")
        if snapshot.rollout_version != expected_rollout:
            raise CapabilityUnavailable("connection rollout snapshot is stale")
        if snapshot.credential_version <= 0:
            raise CapabilityUnavailable("credential version is invalid")
        if not definition.required_scopes.issubset(snapshot.effective_scopes):
            raise CapabilityUnavailable("connection lacks required scopes")
        return CapabilityBinding(
            definition=definition,
            connector=runtime.connector,
            executor=runtime.executor,
            snapshot=snapshot,
        )


def google_definitions():
    scopes = {
        "gmail.send": ("https://www.googleapis.com/auth/gmail.send", ("to", "subject", "body")),
        "gmail.read": ("https://www.googleapis.com/auth/gmail.readonly", ()),
        "calendar.create": ("https://www.googleapis.com/auth/calendar.events", ("summary", "start", "end", "attendees", "event")),
        "calendar.read": ("https://www.googleapis.com/auth/calendar.readonly", ()),
        "drive.upload": ("https://www.googleapis.com/auth/drive.file", ("name", "mime_type")),
        "drive.read": ("https://www.googleapis.com/auth/drive.readonly", ()),
    }
    definitions = []
    schemas = {
        "gmail.send": {
            "type": "object",
            "properties": {
                "raw": {"type": "string", "minLength": 1},
                "to": {"oneOf": [{"type": "string", "minLength": 3}, {"type": "array", "items": {"type": "string", "minLength": 3}, "minItems": 1}]},
                "subject": {"type": "string", "maxLength": 998},
                "body": {"type": "string", "maxLength": 1000000},
            },
            "anyOf": [{"required": ["raw"]}, {"required": ["to", "subject", "body"]}],
            "additionalProperties": False,
        },
        "gmail.read": {"type": "object", "properties": {"max_results": {"type": "integer", "minimum": 1, "maximum": 100}}, "additionalProperties": False},
        "calendar.create": {
            "type": "object",
            "properties": {
                "calendar_id": {"type": "string"}, "event": {"type": "object"},
                "summary": {"type": "string", "minLength": 1},
                "start": {"oneOf": [{"type": "string"}, {"type": "object"}]},
                "end": {"oneOf": [{"type": "string"}, {"type": "object"}]},
                "attendees": {"type": "array", "items": {"type": "string"}},
                "description": {"type": "string"},
            },
            "anyOf": [{"required": ["event"]}, {"required": ["summary", "start", "end"]}],
            "additionalProperties": False,
        },
        "calendar.read": {"type": "object", "properties": {"calendar_id": {"type": "string"}, "timeMin": {"type": "string"}, "timeMax": {"type": "string"}, "maxResults": {"type": "integer", "minimum": 1, "maximum": 2500}}, "additionalProperties": False},
        "drive.upload": {"type": "object", "required": ["name", "content"], "properties": {"name": {"type": "string", "minLength": 1}, "content": {"type": "string"}, "mime_type": {"type": "string"}}, "additionalProperties": False},
        "drive.read": {"type": "object", "properties": {"query": {"type": "string"}, "page_size": {"type": "integer", "minimum": 1, "maximum": 1000}}, "additionalProperties": False},
    }
    for capability_id, (scope, preview_fields) in scopes.items():
        write = capability_id in ("gmail.send", "calendar.create", "drive.upload")
        definitions.append(TrustedCapabilityDefinition(
            capability_id=capability_id,
            version="1.0.0",
            provider="google",
            input_schema=schemas[capability_id],
            output_schema={"type": "object", "additionalProperties": True},
            required_scopes=frozenset({scope}),
            effect="write" if write else "read",
            risk="medium" if write else "low",
            retry_policy="reconcile" if write else "safe",
            preview_fields=preview_fields,
            verifier="google.receipt" if write else None,
        ))
    return tuple(definitions)


def slack_definitions():
    matrix = {
        "slack.channels.list": ("channels:read", "read", (), None),
        "slack.conversation.read": ("channels:history", "read", (), None),
        "slack.thread.read": ("channels:history", "read", (), None),
        "slack.users.list": ("users:read", "read", (), None),
        "slack.message.permalink": ("channels:history", "read", (), None),
        "slack.private_channels.list": ("groups:read", "read", (), None),
        "slack.private_conversation.read": ("groups:history", "read", (), None),
        "slack.private_thread.read": ("groups:history", "read", (), None),
        "slack.message.send": ("chat:write", "write", ("channel_id", "text"), "slack.message"),
        "slack.thread.reply": ("chat:write", "write", ("channel_id", "thread_ts", "text"), "slack.message"),
        "slack.direct_message.send": (("im:write", "chat:write"), "write", ("user_id", "text"), "slack.message"),
        "slack.reaction.add": ("reactions:write", "write", ("channel_id", "message_ts", "reaction"), "slack.reaction"),
        "slack.reaction.remove": ("reactions:write", "write", ("channel_id", "message_ts", "reaction"), "slack.reaction"),
        "slack.message.pin": ("pins:write", "write", ("channel_id", "message_ts"), "slack.pin"),
        "slack.message.unpin": ("pins:write", "write", ("channel_id", "message_ts"), "slack.pin"),
        "slack.bookmark.add": ("bookmarks:write", "write", ("channel_id", "title", "link"), "slack.bookmark"),
        "slack.file.upload": ("files:write", "write", ("channel_id", "filename", "content_hash"), "slack.file"),
    }
    schemas = {
        "slack.channels.list": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200}, "cursor": {"type": "string"}}, "additionalProperties": False},
        "slack.conversation.read": {"type": "object", "required": ["channel_id"], "properties": {"channel_id": {"type": "string"}, "oldest": {"type": "string"}, "latest": {"type": "string"}, "cursor": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "additionalProperties": False},
        "slack.thread.read": {"type": "object", "required": ["channel_id", "thread_ts"], "properties": {"channel_id": {"type": "string"}, "thread_ts": {"type": "string"}, "oldest": {"type": "string"}, "latest": {"type": "string"}, "cursor": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "additionalProperties": False},
        "slack.users.list": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200}, "cursor": {"type": "string"}}, "additionalProperties": False},
        "slack.message.permalink": {"type": "object", "required": ["channel_id", "message_ts"], "properties": {"channel_id": {"type": "string"}, "message_ts": {"type": "string"}}, "additionalProperties": False},
        "slack.private_channels.list": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200}}, "additionalProperties": False},
        "slack.private_conversation.read": {"type": "object", "required": ["channel_id"], "properties": {"channel_id": {"type": "string"}, "limit": {"type": "integer"}}, "additionalProperties": False},
        "slack.private_thread.read": {"type": "object", "required": ["channel_id", "thread_ts"], "properties": {"channel_id": {"type": "string"}, "thread_ts": {"type": "string"}, "limit": {"type": "integer"}}, "additionalProperties": False},
        "slack.message.send": {"type": "object", "required": ["channel_id", "text"], "properties": {"channel_id": {"type": "string"}, "text": {"type": "string", "maxLength": 40000}}, "additionalProperties": False},
        "slack.thread.reply": {"type": "object", "required": ["channel_id", "thread_ts", "text"], "properties": {"channel_id": {"type": "string"}, "thread_ts": {"type": "string"}, "text": {"type": "string", "maxLength": 40000}}, "additionalProperties": False},
        "slack.direct_message.send": {"type": "object", "required": ["user_id", "text"], "properties": {"user_id": {"type": "string"}, "text": {"type": "string", "maxLength": 40000}}, "additionalProperties": False},
        "slack.reaction.add": {"type": "object", "required": ["channel_id", "message_ts", "reaction"], "properties": {"channel_id": {"type": "string"}, "message_ts": {"type": "string"}, "reaction": {"type": "string"}}, "additionalProperties": False},
        "slack.reaction.remove": {"type": "object", "required": ["channel_id", "message_ts", "reaction"], "properties": {"channel_id": {"type": "string"}, "message_ts": {"type": "string"}, "reaction": {"type": "string"}}, "additionalProperties": False},
        "slack.message.pin": {"type": "object", "required": ["channel_id", "message_ts"], "properties": {"channel_id": {"type": "string"}, "message_ts": {"type": "string"}}, "additionalProperties": False},
        "slack.message.unpin": {"type": "object", "required": ["channel_id", "message_ts"], "properties": {"channel_id": {"type": "string"}, "message_ts": {"type": "string"}}, "additionalProperties": False},
        "slack.bookmark.add": {"type": "object", "required": ["channel_id", "title", "link"], "properties": {"channel_id": {"type": "string"}, "title": {"type": "string", "minLength": 1, "maxLength": 250}, "link": {"type": "string", "pattern": "^https://"}}, "additionalProperties": False},
        "slack.file.upload": {"type": "object", "required": ["channel_id", "filename", "content_hash"], "properties": {"channel_id": {"type": "string"}, "filename": {"type": "string"}, "content_hash": {"type": "string"}, "content": {"type": "string"}}, "additionalProperties": False},
    }
    nullable_string = {"type": ["string", "null"]}
    channel = {
        "type": "object",
        "required": ["id", "name", "is_private"],
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"},
            "is_private": {"type": "boolean"},
        },
        "additionalProperties": False,
    }
    message = {
        "type": "object",
        "required": ["ts", "text", "user", "thread_ts"],
        "properties": {
            "ts": nullable_string,
            "text": {"type": "string"},
            "user": nullable_string,
            "thread_ts": nullable_string,
        },
        "additionalProperties": False,
    }
    user = {
        "type": "object",
        "required": ["id", "handle", "display_name", "real_name"],
        "properties": {
            "id": {"type": "string"},
            "handle": nullable_string,
            "display_name": {"type": "string"},
            "real_name": {"type": "string"},
            "image_url": {"type": "string"},
        },
        "additionalProperties": False,
    }

    def page_output(field, item_schema):
        return {
            "type": "object",
            "required": [field, "next_cursor", "partial"],
            "properties": {
                field: {"type": "array", "items": item_schema},
                "next_cursor": nullable_string,
                "partial": {"type": "boolean"},
            },
            "additionalProperties": False,
        }

    def receipt_output(capability_id, extra_properties=None):
        properties = {
            "provider": {"type": "string", "const": "slack"},
            "capability_id": {"type": "string", "const": capability_id},
            "provider_id": {"type": "string"},
            "team_id": nullable_string,
            "channel_id": {"type": "string"},
        }
        properties.update(extra_properties or {})
        return {
            "type": "object",
            "required": list(properties),
            "properties": properties,
            "additionalProperties": False,
        }

    output_schemas = {
        "slack.channels.list": page_output("channels", channel),
        "slack.private_channels.list": page_output("channels", channel),
        "slack.conversation.read": page_output("messages", message),
        "slack.private_conversation.read": page_output("messages", message),
        "slack.thread.read": page_output("messages", message),
        "slack.private_thread.read": page_output("messages", message),
        "slack.users.list": page_output("users", user),
        "slack.message.permalink": {
            "type": "object",
            "required": ["channel_id", "message_ts", "permalink"],
            "properties": {
                "channel_id": {"type": "string"},
                "message_ts": {"type": "string"},
                "permalink": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "slack.message.send": receipt_output(
            "slack.message.send", {"message_ts": {"type": "string"}}
        ),
        "slack.thread.reply": receipt_output(
            "slack.thread.reply", {"message_ts": {"type": "string"}}
        ),
        "slack.direct_message.send": receipt_output(
            "slack.direct_message.send", {
                "message_ts": {"type": "string"},
                "user_id": {"type": "string"},
            },
        ),
        "slack.reaction.add": receipt_output(
            "slack.reaction.add", {
                "message_ts": {"type": "string"},
                "reaction": {"type": "string"},
            },
        ),
        "slack.reaction.remove": receipt_output(
            "slack.reaction.remove", {
                "message_ts": {"type": "string"},
                "reaction": {"type": "string"},
            },
        ),
        "slack.message.pin": receipt_output(
            "slack.message.pin", {"message_ts": {"type": "string"}},
        ),
        "slack.message.unpin": receipt_output(
            "slack.message.unpin", {"message_ts": {"type": "string"}},
        ),
        "slack.bookmark.add": receipt_output(
            "slack.bookmark.add", {
                "bookmark_id": {"type": "string"},
                "title": {"type": "string"},
            },
        ),
        "slack.file.upload": receipt_output(
            "slack.file.upload", {
                "provider_id": nullable_string,
                "file_id": nullable_string,
            },
        ),
    }
    return tuple(TrustedCapabilityDefinition(
        capability_id=capability_id,
        version="1.0.0",
        provider="slack",
        input_schema=schemas[capability_id],
        output_schema=output_schemas[capability_id],
        # A capability declares every scope its executor needs, not just the
        # headline one. Slack's DM send opens a conversation and then posts to
        # it; modelling that as one scope lets a workspace pass the check and
        # fail at the provider.
        required_scopes=frozenset(
            (scope,) if isinstance(scope, str) else scope
        ),
        effect=effect,
        risk="medium" if effect == "write" else "low",
        retry_policy="reconcile" if effect == "write" else "safe",
        preview_fields=preview,
        verifier=verifier,
    ) for capability_id, (scope, effect, preview, verifier) in matrix.items())
