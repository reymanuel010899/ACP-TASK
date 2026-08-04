"""Authority-separated capability catalog and native provider registry.

Only :class:`TrustedCapabilityDefinition` values can bind executable code.
Connection snapshots are live tenant authority.  External offers are
discovery input only and intentionally cannot enter the runtime registry.
"""

import json
from dataclasses import dataclass
from typing import Any, Callable, FrozenSet, Mapping, Optional, Tuple


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
    #: Which authority a dispatch must act as. Declared here so the catalog
    #: stays the single source of truth, rather than a second copy that can
    #: drift the way the install scope list already did.
    authority_profile: str = "bot"
    #: Effects whose approval must come from someone provably present. Channel
    #: administration reshapes shared space for everyone in it, so a session
    #: left open all day is not consent.
    reinforced: bool = False

    def __post_init__(self):
        if not self.capability_id or "." not in self.capability_id:
            raise ValueError("a namespaced capability_id is required")
        if self.effect not in ("read", "write"):
            raise ValueError("effect must be read or write")
        if self.effect == "write" and not self.preview_fields:
            raise ValueError("write capabilities require preview fields")
        if self.authority_profile not in ("bot", "user", "enterprise_admin"):
            raise ValueError("unsupported authority profile")


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
class ProviderAuthority:
    """Short-lived authority to act at one provider, plus what it may do."""

    access_token: str
    granted_scopes: FrozenSet[str] = frozenset()


class CredentialStrategy(object):
    """Turn one sealed vault secret into short-lived provider authority.

    Every provider seals something, but not the same thing: an OAuth refresh
    token must be exchanged, a workspace install token already is the
    authority, and an account-identifier-plus-token pair is neither. Naming
    that per runtime is what keeps the dispatch path from growing one branch
    per provider, which is how it read before.
    """

    name = "credential"

    def authority(self, secret, connector=None):
        raise NotImplementedError


class RefreshedOAuthCredential(CredentialStrategy):
    """Exchange a sealed refresh token for a short-lived access token."""

    name = "oauth_refresh"

    def authority(self, secret, connector=None):
        if connector is None:
            raise PermissionError("credential refresh is not configured")
        refreshed = connector.refresh(secret.decode("utf-8"))
        return ProviderAuthority(
            access_token=refreshed.access_token,
            granted_scopes=frozenset(refreshed.granted_scopes or ()),
        )


class SealedTokenDocumentCredential(CredentialStrategy):
    """Read authority straight out of the sealed document.

    Some providers issue no refresh exchange at all, so the sealed document is
    the authority rather than a way of obtaining one. Reading it here rather
    than in the broker means the next such provider adds a registration, not
    a branch.
    """

    name = "sealed_document"

    def authority(self, secret, connector=None):
        try:
            document = json.loads(secret.decode("utf-8"))
        except (AttributeError, TypeError, ValueError, UnicodeDecodeError) as exc:
            raise PermissionError(
                "sealed credential document is invalid"
            ) from exc
        if not isinstance(document, dict):
            raise PermissionError("sealed credential document is invalid")
        access_token = document.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise PermissionError("provider access authority is unavailable")
        return ProviderAuthority(
            access_token=access_token,
            granted_scopes=frozenset(document.get("granted_scopes") or ()),
        )


REFRESHED_OAUTH_CREDENTIAL = RefreshedOAuthCredential()
SEALED_TOKEN_DOCUMENT_CREDENTIAL = SealedTokenDocumentCredential()


@dataclass(frozen=True)
class ProviderRuntime:
    provider: str
    connector: Any
    executor: Any
    definitions: Tuple[TrustedCapabilityDefinition, ...]
    #: How this provider's sealed secret becomes provider authority. Declared
    #: with the runtime so the broker never asks which provider it is holding.
    credential_strategy: CredentialStrategy = REFRESHED_OAUTH_CREDENTIAL

    def __post_init__(self):
        if not self.provider or self.connector is None or self.executor is None:
            raise ValueError("provider, connector and executor are required")
        if not isinstance(self.credential_strategy, CredentialStrategy):
            raise TypeError("runtime credential strategy must be trusted")
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
    credential_strategy: CredentialStrategy = REFRESHED_OAUTH_CREDENTIAL


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
            credential_strategy=runtime.credential_strategy,
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


#: Writes Slack itself treats as set-state rather than append. Repeating one
#: converges on the same result, so an ambiguous dispatch can simply retry
#: instead of demanding reconciliation. Sending a message is not here: a
#: repeat posts twice.
#: Channel administration reshapes space shared by everyone in it, so its
#: approval must come from someone provably present rather than from a session
#: that happens to still be valid.
REINFORCED_CAPABILITIES = frozenset({
    "slack.channel.create", "slack.channel.rename",
    "slack.channel.set_topic", "slack.channel.archive",
    "slack.channel.invite",
})

#: Capabilities that act as a person rather than as the installation. Slack's
#: message search reads what one user can see, so a bot token cannot stand in
#: for it without silently widening or narrowing the result.
USER_AUTHORITY_CAPABILITIES = frozenset({"slack.search.messages"})

IDEMPOTENT_WRITES = frozenset({
    "slack.reaction.add", "slack.reaction.remove",
    "slack.message.pin", "slack.message.unpin",
})


def capability_reinforced(capability_id):
    """Whether approving this effect requires someone provably present."""
    return capability_id in REINFORCED_CAPABILITIES


def capability_retry_policy(capability_id, effect):
    if effect != "write":
        return "safe"
    return "idempotent" if capability_id in IDEMPOTENT_WRITES else "reconcile"


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
        "slack.search.messages": ("search:read", "read", (), None),
        "slack.channel.create": ("channels:manage", "write", ("name", "is_private"), "slack.channel"),
        "slack.channel.rename": ("channels:manage", "write", ("channel_id", "name"), "slack.channel"),
        "slack.channel.set_topic": ("channels:manage", "write", ("channel_id", "topic"), "slack.channel"),
        "slack.channel.archive": ("channels:manage", "write", ("channel_id",), "slack.channel"),
        "slack.channel.invite": ("channels:manage", "write", ("channel_id", "user_ids"), "slack.channel"),
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
        "slack.channel.create": {"type": "object", "required": ["name"], "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 80, "pattern": "^[a-z0-9_-]+$"}, "is_private": {"type": "boolean"}}, "additionalProperties": False},
        "slack.channel.rename": {"type": "object", "required": ["channel_id", "name"], "properties": {"channel_id": {"type": "string"}, "name": {"type": "string", "minLength": 1, "maxLength": 80, "pattern": "^[a-z0-9_-]+$"}}, "additionalProperties": False},
        "slack.channel.set_topic": {"type": "object", "required": ["channel_id", "topic"], "properties": {"channel_id": {"type": "string"}, "topic": {"type": "string", "maxLength": 250}}, "additionalProperties": False},
        "slack.channel.archive": {"type": "object", "required": ["channel_id"], "properties": {"channel_id": {"type": "string"}}, "additionalProperties": False},
        "slack.channel.invite": {"type": "object", "required": ["channel_id", "user_ids"], "properties": {"channel_id": {"type": "string"}, "user_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 100}}, "additionalProperties": False},
        "slack.search.messages": {"type": "object", "required": ["query"], "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 500}, "cursor": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "additionalProperties": False},
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
        "slack.search.messages": page_output("messages", message),
        "slack.channel.create": receipt_output("slack.channel.create", {"name": {"type": "string"}}),
        "slack.channel.rename": receipt_output("slack.channel.rename", {"name": {"type": "string"}}),
        "slack.channel.set_topic": receipt_output("slack.channel.set_topic", {"topic": {"type": "string"}}),
        "slack.channel.archive": receipt_output("slack.channel.archive", {}),
        "slack.channel.invite": receipt_output("slack.channel.invite", {"invited": {"type": "integer"}}),
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
        retry_policy=capability_retry_policy(capability_id, effect),
        preview_fields=preview,
        verifier=verifier,
        authority_profile=(
            "user" if capability_id in USER_AUTHORITY_CAPABILITIES else "bot"
        ),
        reinforced=capability_id in REINFORCED_CAPABILITIES,
    ) for capability_id, (scope, effect, preview, verifier) in matrix.items())


@dataclass(frozen=True)
class ProviderRegistration:
    """Everything provider-specific that is not a secret, in one place.

    Composition sites used to name each provider's definitions individually,
    so adding one meant editing every site and forgetting one meant a
    capability the planner could see and the broker could not execute.
    """

    provider: str
    definitions: Callable[[], Tuple[TrustedCapabilityDefinition, ...]]
    credential_strategy: CredentialStrategy = REFRESHED_OAUTH_CREDENTIAL
    #: The manifest version this provider's conversational operations speak,
    #: or ``None`` while the provider has no operation manifest yet.
    manifest_version: Optional[str] = None


PROVIDER_REGISTRATIONS = (
    ProviderRegistration(
        provider="google",
        definitions=google_definitions,
        credential_strategy=REFRESHED_OAUTH_CREDENTIAL,
    ),
    ProviderRegistration(
        provider="slack",
        definitions=slack_definitions,
        # A workspace install token has no refresh exchange, so the sealed
        # document is the authority rather than a way of getting one.
        credential_strategy=SEALED_TOKEN_DOCUMENT_CREDENTIAL,
        manifest_version="slack.operations.v1",
    ),
)

_REGISTRATIONS_BY_PROVIDER = {
    registration.provider: registration
    for registration in PROVIDER_REGISTRATIONS
}


def registered_providers():
    return tuple(registration.provider for registration in PROVIDER_REGISTRATIONS)


def provider_registration(provider):
    """Fail closed on an unregistered provider rather than degrade quietly."""
    registration = _REGISTRATIONS_BY_PROVIDER.get(provider)
    if registration is None:
        raise CapabilityUnavailable("provider is not registered")
    return registration


def provider_definitions(*providers):
    """Trusted definitions for the named providers, or for all of them.

    One registration point, so a new provider is added once instead of at
    every composition site that happened to list the existing two.
    """
    names = providers or registered_providers()
    definitions = []
    for provider in names:
        definitions.extend(provider_registration(provider).definitions())
    return tuple(definitions)


def credential_strategy_for(provider):
    return provider_registration(provider).credential_strategy
