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


#: Which authority a dispatch acts as.
#:
#: ``bot`` acts as the installation, ``user`` as one person who consented,
#: ``enterprise_admin`` as an org-wide administrator. ``account`` acts as the
#: tenant's provider account itself: there is no consenting person and no
#: installation, only an account identifier and an auth token whose authority
#: is whatever the account has been verified to hold.
AUTHORITY_PROFILES = ("bot", "user", "enterprise_admin", "account")


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
        if self.authority_profile not in AUTHORITY_PROFILES:
            raise ValueError("unsupported authority profile")


@dataclass(frozen=True)
class ConnectionCapabilitySnapshot:
    connection_id: str
    tenant_id: str
    capability_id: str
    capability_version: str
    #: Custody generation of the sealed secret, counted from one.
    #:
    #: It answers exactly one question: is the secret this binding was made
    #: against still the secret the connection holds? It therefore moves only
    #: when the secret material is replaced — an OAuth refresh rotation, or an
    #: operator re-sealing a manually rotated static credential after changing
    #: it in the provider's console. It deliberately does not move when
    #: authority changes, because authority lives in ``effective_scopes``:
    #: bumping it to express a lawful narrowing would fail every queued effect
    #: on the whole connection with a tampering-shaped reason.
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


#: Dimensions a synthetic scope can name besides a capability family. A
#: sending identity, a destination geography, and an approved message template
#: are the three things a provider verifies independently of any consent.
SENDER_DIMENSION = "sender"
GEO_DIMENSION = "geo"
TEMPLATE_DIMENSION = "template"
#: The branch of the contacts tree an effect is allowed to touch. Unlike the
#: three above it names authority inside our own store rather than at a
#: provider, which is exactly why it is a scope and not a bespoke check: a
#: branch the requester may not view is then absent from the connection's
#: effective scopes, and every subset test already on the dispatch path
#: refuses the effect without knowing what a branch is.
BRANCH_DIMENSION = "branch"

#: An account is authority-bearing only while it is verified. ``unavailable``
#: is the fail-closed state: the account could not be checked, so it holds no
#: authority rather than its last known authority.
ACCOUNT_STATUSES = ("verified", "unverified", "suspended", "unavailable")


def synthetic_scope(provider, dimension, value):
    """Name one unit of authority a provider with no scope system still has.

    The whole authority spine is scope-shaped — both the policy evaluator and
    the runtime registry decide by asking whether a definition's required
    scopes are a subset of the connection's effective scopes — so a provider
    that issues no scopes cannot express authority at all until its authority
    is given scope shape. These are that shape: namespaced, flat strings that
    travel through the existing checks untouched.
    """
    parts = (provider, dimension, value)
    if not all(isinstance(part, str) and part for part in parts):
        raise ValueError("a synthetic scope needs provider, dimension and value")
    if any(":" in part for part in parts[:2]):
        raise ValueError("provider and dimension must not contain a separator")
    return "%s:%s:%s" % parts


@dataclass(frozen=True)
class VerifiedSender:
    """One sending identity the provider has verified for this account."""

    sender_id: str
    family: str
    countries: FrozenSet[str] = frozenset()
    #: Enablement is authority, not visibility. A disabled sender contributes
    #: no scope at all, which is what makes disabling one expressible as the
    #: removal of a single scope.
    enabled: bool = True


@dataclass(frozen=True)
class VerifiedAccountState:
    """What a provider account verifiably holds, at one moment in time.

    Read from the account, never from a consent callback, because a provider
    authenticated by an account identifier and an auth token has no callback.
    It is read at connection time and again on every re-verification, since
    account state moves without anyone visiting a browser.
    """

    provider: str
    account_id: str
    status: str = "unavailable"
    #: ``family:action`` pairs the account may perform, e.g. ``sms:send``.
    families: FrozenSet[str] = frozenset()
    senders: Tuple[VerifiedSender, ...] = ()
    templates: FrozenSet[str] = frozenset()

    def __post_init__(self):
        if not self.provider or not self.account_id:
            raise ValueError("a verified account needs a provider and an id")
        if self.status not in ACCOUNT_STATUSES:
            raise ValueError("unsupported provider account status")
        for family in self.families:
            name, separator, action = family.partition(":")
            if not name or not separator or not action:
                raise ValueError("a family must be named family:action")


def account_state(value):
    """Build verified account state from a connector's plain mapping.

    Connectors stay free of catalog types; the catalog stays the only place
    that decides what counts as verified authority.
    """
    if isinstance(value, VerifiedAccountState):
        return value
    if not isinstance(value, Mapping):
        raise CapabilityUnavailable("verified account state is required")
    senders = []
    for sender in value.get("senders") or ():
        if isinstance(sender, VerifiedSender):
            senders.append(sender)
            continue
        if not isinstance(sender, Mapping):
            raise CapabilityUnavailable("verified account state is malformed")
        senders.append(VerifiedSender(
            sender_id=sender.get("sender_id"),
            family=sender.get("family"),
            countries=frozenset(sender.get("countries") or ()),
            enabled=bool(sender.get("enabled", True)),
        ))
    try:
        return VerifiedAccountState(
            provider=value["provider"],
            account_id=value["account_id"],
            status=value.get("status", "unavailable"),
            families=frozenset(value.get("families") or ()),
            senders=tuple(senders),
            templates=frozenset(value.get("templates") or ()),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CapabilityUnavailable(
            "verified account state is malformed"
        ) from exc


def derive_synthetic_scopes(state):
    """Turn verified account state into the scopes that account may use.

    Fails closed in both directions. An account that is not verified derives
    nothing, so an unreachable provider account cannot dispatch. A disabled
    sender derives nothing, so disabling one sender removes exactly one sender
    scope — every in-flight binding naming it stops passing the subset check
    that already guards dispatch, while bindings naming a different sender on
    the same connection are untouched.
    """
    state = account_state(state)
    if state.status != "verified":
        return frozenset()
    scopes = set()
    live_families = set()
    for family in state.families:
        name, _separator, action = family.partition(":")
        live_families.add(name)
        scopes.add(synthetic_scope(state.provider, name, action))
    for sender in state.senders:
        if not sender.enabled:
            continue
        # A sender whose family is not live carries no authority: enabling the
        # number and enabling the family are separate acts, and the narrower
        # one wins.
        if sender.family not in live_families:
            continue
        scopes.add(
            synthetic_scope(state.provider, SENDER_DIMENSION, sender.sender_id)
        )
        for country in sender.countries:
            scopes.add(
                synthetic_scope(state.provider, GEO_DIMENSION, country)
            )
    for template in state.templates:
        scopes.add(
            synthetic_scope(state.provider, TEMPLATE_DIMENSION, template)
        )
    return frozenset(scopes)


@dataclass(frozen=True)
class ProviderAuthority:
    """Short-lived authority to act at one provider, plus what it may do."""

    access_token: str
    granted_scopes: FrozenSet[str] = frozenset()
    #: Which provider account the token belongs to, for providers whose
    #: identity is the account rather than an installation or a person. The
    #: executor needs it to address the right account, and the policy
    #: evaluator binds it so a dispatch cannot swap accounts after approval.
    account_id: Optional[str] = None


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


class StaticAccountCredential(CredentialStrategy):
    """An account identifier plus a long-lived auth token, sealed together.

    Nothing is exchanged and nothing is refreshed: the sealed document is both
    the identity and the secret. The scopes it carries are the synthetic ones
    derived from the account's verified state at connection or re-verification
    time, not anything a consent screen returned — which is why re-verifying
    an account is what changes authority here, and why the credential version
    stays put while it does.
    """

    name = "static_account"

    def authority(self, secret, connector=None):
        del connector  # There is no exchange to make and no token to refresh.
        try:
            document = json.loads(secret.decode("utf-8"))
        except (AttributeError, TypeError, ValueError, UnicodeDecodeError) as exc:
            raise PermissionError(
                "sealed credential document is invalid"
            ) from exc
        if not isinstance(document, dict):
            raise PermissionError("sealed credential document is invalid")
        account_id = document.get("account_id")
        auth_token = document.get("auth_token")
        if not isinstance(account_id, str) or not account_id:
            raise PermissionError("provider account identity is unavailable")
        if not isinstance(auth_token, str) or not auth_token:
            raise PermissionError("provider access authority is unavailable")
        return ProviderAuthority(
            access_token=auth_token,
            granted_scopes=frozenset(document.get("granted_scopes") or ()),
            account_id=account_id,
        )


class FirstPartyStoreCredential(CredentialStrategy):
    """There is no provider, so there is no provider authority to mint.

    A first-party store is reached in-process through a tenant-bound
    repository whose row-level security is the authority. Nothing is sealed,
    nothing is exchanged, and nothing may be handed to an outbound HTTP path.
    Refusing here rather than returning an empty token is deliberate: if a
    contacts capability ever reaches the external dispatch path, the correct
    outcome is a loud failure, not a request carrying a blank credential.
    """

    name = "first_party_store"

    def authority(self, secret, connector=None):
        del secret, connector
        raise PermissionError(
            "a first-party store issues no provider authority"
        )


REFRESHED_OAUTH_CREDENTIAL = RefreshedOAuthCredential()
SEALED_TOKEN_DOCUMENT_CREDENTIAL = SealedTokenDocumentCredential()
STATIC_ACCOUNT_CREDENTIAL = StaticAccountCredential()
FIRST_PARTY_STORE_CREDENTIAL = FirstPartyStoreCredential()


class FirstPartyStore(object):
    """Stands where an external connector would, and refuses to act as one.

    ``ProviderRuntime`` requires a connector, because every provider so far
    has had one. This one exists to make the absence explicit rather than to
    supply a ``None`` that some later branch would have to special-case.
    """

    provider = None

    def __init__(self, provider):
        self.provider = provider

    def refresh(self, *args, **kwargs):
        del args, kwargs
        raise PermissionError(
            "a first-party store has no credential to refresh"
        )


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


#: The first-party contacts directory. Not a provider in the sense the other
#: two are -- there is no external service, no installation, and no consent
#: screen -- but it must be one here, because every executable capability in
#: this codebase is reached through the same registry, and carving an
#: exception into that registry is how the authority join grows a second
#: implementation.
CONTACTS_PROVIDER = "contacts"
TWILIO_PROVIDER = "twilio"


def twilio_definitions():
    address = {"type": "string", "pattern": r"^\+?[1-9][0-9]{7,14}$"}
    common = {
        "contact_id": {"type": "string", "minLength": 1},
        "contact_version": {"type": "string", "minLength": 1},
        "address_id": {"type": "string", "minLength": 1},
        "to": address,
        "from": address,
        "status_callback": {"type": "string", "pattern": "^https://"},
        "purpose": {"type": "string", "minLength": 1},
    }
    schemas = {
        "twilio.voice.call": {
            "type": "object",
            "required": ["contact_id", "contact_version", "address_id", "to", "from",
                         "status_callback", "twiml_url", "purpose", "definition_hash",
                         "maximum_duration_seconds", "ring_timeout_seconds", "recording"],
            "properties": dict(common,
                twiml_url={"type": "string", "pattern": "^https://"},
                definition_hash={"type": "string", "pattern": "^[0-9a-f]{64}$"},
                maximum_duration_seconds={"type": "integer", "minimum": 15, "maximum": 7200},
                ring_timeout_seconds={"type": "integer", "minimum": 5, "maximum": 600},
                recording={"type": "boolean"},
            ), "additionalProperties": False,
        },
        "twilio.sms.send": {
            "type": "object", "required": list(common) + ["body"],
            "properties": dict(common, body={"type": "string", "minLength": 1, "maxLength": 1600}),
            "additionalProperties": False,
        },
        "twilio.whatsapp.freeform.send": {
            "type": "object", "required": list(common) + ["body"],
            "properties": dict(common, body={"type": "string", "minLength": 1, "maxLength": 4096}),
            "additionalProperties": False,
        },
        "twilio.whatsapp.template.send": {
            "type": "object", "required": list(common) + ["content_sid", "content_variables", "template_category"],
            "properties": dict(common,
                content_sid={"type": "string", "pattern": "^HX[0-9a-fA-F]{32}$"},
                content_variables={"type": "object", "additionalProperties": {"type": "string"}},
                template_category={"type": "string", "enum": ["marketing", "utility", "authentication"]},
            ), "additionalProperties": False,
        },
    }
    required_scope = {
        "twilio.voice.call": "twilio:voice:call",
        "twilio.sms.send": "twilio:sms:send",
        "twilio.whatsapp.freeform.send": "twilio:whatsapp:freeform",
        "twilio.whatsapp.template.send": "twilio:whatsapp:template",
    }
    definitions = []
    for capability_id, schema in schemas.items():
        definitions.append(TrustedCapabilityDefinition(
            capability_id=capability_id, version="1.0.0", provider=TWILIO_PROVIDER,
            input_schema=schema,
            output_schema={
                "type": "object", "required": ["provider", "capability_id", "provider_id", "status"],
                "properties": {
                    "provider": {"const": "twilio"},
                    "capability_id": {"const": capability_id},
                    "provider_id": {"type": "string"}, "status": {"type": "string"},
                }, "additionalProperties": False,
            },
            required_scopes=frozenset({required_scope[capability_id]}),
            effect="write", risk="high", retry_policy="reconcile",
            preview_fields=(
                "contact_id", "contact_version", "to", "from", "definition_hash",
                "maximum_duration_seconds", "recording",
            ) if capability_id == "twilio.voice.call" else (
                "contact_id", "contact_version", "to", "from", "body"
            ) if "body" in schema["properties"] else (
                "contact_id", "contact_version", "to", "from",
                "content_sid", "content_variables",
            ),
            verifier="twilio.delivery", authority_profile="account",
        ))
    return tuple(definitions)

#: Families the contacts store verifiably holds for every bound tenant. They
#: exist for the same reason Twilio's do: the authority spine is scope-shaped,
#: so an authority that issues no scopes cannot be expressed until it is given
#: scope shape (KTD2). Reads and writes are separate families so an account
#: can hold the read surface without the propose surface.
CONTACTS_FAMILIES = (
    "directory:read",
    "grouping:read",
    "consent:read",
    "activity:read",
    "audience:preview",
    "proposal:write",
    "grouping:write",
)

#: A first-party connection has no sealed secret, so it has no custody
#: generation to count. It is pinned at one rather than left at zero because
#: ``resolve`` and the policy evaluator both refuse a non-positive credential
#: version, and because a value that never moves is the honest description:
#: there is no secret whose replacement could move it.
FIRST_PARTY_CREDENTIAL_VERSION = 1

#: Identifier shapes the contacts capabilities accept. They are patterns, not
#: prose, because this is the second half of the guard in
#: ``agents/orchestrator/workflow_models.py``: that one stops a model emitting
#: a destination, and this one stops anything that is not a resolver output
#: from reaching an input named for one. A phone number does not match any of
#: these, so it cannot enter through a slot that was meant to hold an id.
_ULID = "[0-9A-HJKMNP-TV-Z]{26}"
CONTACT_ID_PATTERN = "^contact:%s$" % _ULID
BRANCH_ID_PATTERN = "^branch:%s$" % _ULID
ADDRESS_ID_PATTERN = "^address:%s$" % _ULID
LIST_ID_PATTERN = "^list:%s$" % _ULID
TAG_ID_PATTERN = "^tag:%s$" % _ULID
SEGMENT_ID_PATTERN = "^segment:%s$" % _ULID
#: A server-issued handle on text the requester typed, minted where the turn
#: is received. A proposal names one of these instead of an address, so the
#: only path from natural language to a destination runs through a capture the
#: model never saw and cannot invent.
ADDRESS_CAPTURE_PATTERN = "^capture:%s$" % _ULID


def contacts_account_state(tenant_id, families=CONTACTS_FAMILIES):
    """What the contacts store verifiably holds for one bound tenant.

    Bound is the whole condition. There is no provider to ask, so the fact
    being verified is that a tenant was resolved at all -- which is precisely
    the failure KTD11 names, where an unmapped principal silently lands in a
    local tenant. Here an unbound principal derives an account that is not
    verified, an unverified account derives no scopes, and no scopes means no
    contacts capability resolves.
    """
    bound = isinstance(tenant_id, str) and bool(tenant_id.strip())
    return VerifiedAccountState(
        provider=CONTACTS_PROVIDER,
        account_id=tenant_id if bound else "unbound",
        status="verified" if bound else "unavailable",
        families=frozenset(families or ()),
    )


def contacts_scopes(tenant_id, branch_ids=(), families=CONTACTS_FAMILIES):
    """Derive one tenant's contacts authority, families plus branches.

    The family scopes come out of U3's derivation untouched. The branch scopes
    are composed on top rather than folded into ``VerifiedAccountState``,
    because a branch is not a sending identity, a geography, or a template,
    and widening that dataclass to hold a fourth unrelated dimension would
    make Twilio's verified state carry a field it can never populate.
    """
    scopes = set(derive_synthetic_scopes(contacts_account_state(
        tenant_id, families,
    )))
    if not scopes:
        # An unbound tenant holds nothing at all, so it cannot hold branches
        # either. Adding them here would hand out exactly the authority the
        # unverified account was refused.
        return frozenset()
    for branch_id in branch_ids or ():
        scopes.add(
            synthetic_scope(CONTACTS_PROVIDER, BRANCH_DIMENSION, branch_id)
        )
    return frozenset(scopes)


def first_party_connection_id(provider, tenant_id):
    return "first-party:%s:%s" % (provider, tenant_id)


def first_party_connection_snapshot(
    tenant_id, capability_id, capability_version, rollout_version,
    branch_ids=(), families=CONTACTS_FAMILIES, provider=CONTACTS_PROVIDER,
):
    """Mint the connection a first-party store does not have.

    ``ProviderRuntimeRegistry.resolve`` demands a connection identifier, a
    positive credential version, effective scopes, health, and a matching
    rollout -- every one of which describes an external integration the
    contacts directory does not have. Declaring the operations ``local`` is
    not an escape, because a local operation may not declare a capability
    recipe and therefore may not execute anything.

    So the connection is synthesised, per tenant, from what is actually
    verifiable about a first-party store: which tenant is bound, which
    branches that tenant's requester may act on, and the fact that there is no
    secret to have rotated. It travels through every existing check unchanged.
    """
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise CapabilityUnavailable("a bound tenant is required")
    scopes = contacts_scopes(tenant_id, branch_ids, families)
    if not scopes:
        raise CapabilityUnavailable("first-party account holds no authority")
    return ConnectionCapabilitySnapshot(
        connection_id=first_party_connection_id(provider, tenant_id),
        tenant_id=tenant_id,
        capability_id=capability_id,
        capability_version=capability_version,
        credential_version=FIRST_PARTY_CREDENTIAL_VERSION,
        effective_scopes=scopes,
        health="healthy",
        rollout_version=rollout_version,
    )


def contacts_definitions():
    """The read and propose surface, carved by entity kind and verb.

    There is no ``contacts.create`` and no ``contacts.update``. An agent-side
    mutation is one capability per mutation class that always lands in the
    review queue, rather than a pair of "with approval" and "without approval"
    variants of every verb -- which is how a surface acquires a path that
    skips the human by construction. The two organizational writes are the
    stated exception: adding someone to a list and applying a tag are
    reversible, carry no consent semantics, and reach nobody.
    """
    contact_id = {"type": "string", "pattern": CONTACT_ID_PATTERN}
    branch_id = {"type": "string", "pattern": BRANCH_ID_PATTERN}
    list_id = {"type": "string", "pattern": LIST_ID_PATTERN}
    tag_id = {"type": "string", "pattern": TAG_ID_PATTERN}
    segment_id = {"type": "string", "pattern": SEGMENT_ID_PATTERN}
    channel = {"type": "string", "enum": ["sms", "whatsapp", "voice", "email"]}
    purpose = {
        "type": "string",
        "enum": [
            "marketing", "utility", "authentication", "transactional",
            "service",
        ],
    }
    query = {"type": "string", "minLength": 1, "maxLength": 200}
    limit = {"type": "integer", "minimum": 1, "maximum": 200}

    masked_destination = {
        "type": "object",
        "required": ["channel", "text", "fingerprint"],
        "properties": {
            "channel": {"type": "string"},
            "text": {"type": "string"},
            "country_code": {"type": ["string", "null"]},
            "digit_count": {"type": ["integer", "null"]},
            "visible_tail": {"type": ["string", "null"]},
            "fingerprint": {"type": "string"},
            "branch_path": {"type": ["string", "null"]},
            "last_contacted_at": {"type": ["string", "null"]},
        },
        "additionalProperties": False,
    }
    candidate = {
        "type": "object",
        "required": [
            "contact_id", "record_version", "display_name", "branch_path",
            "destinations", "consent", "effect_ready",
        ],
        "properties": {
            "contact_id": {"type": "string"},
            "record_version": {"type": "string"},
            "display_name": {"type": "string"},
            "branch_path": {"type": ["string", "null"]},
            "destinations": {"type": "array", "items": masked_destination},
            "consent": {"type": "object"},
            "effect_ready": {"type": "boolean"},
            "matched_by": {"type": ["string", "null"]},
        },
        "additionalProperties": False,
    }
    receipt = {
        "type": "object",
        "required": ["provider", "capability_id", "proposal_id", "state"],
        "properties": {
            "provider": {"type": "string", "const": CONTACTS_PROVIDER},
            "capability_id": {"type": "string"},
            "proposal_id": {"type": "string"},
            "state": {"type": "string"},
            "contact_id": {"type": ["string", "null"]},
        },
        "additionalProperties": False,
    }
    grouping_receipt = {
        "type": "object",
        "required": ["provider", "capability_id", "contact_id", "grouping_id"],
        "properties": {
            "provider": {"type": "string", "const": CONTACTS_PROVIDER},
            "capability_id": {"type": "string"},
            "contact_id": {"type": "string"},
            "grouping_id": {"type": "string"},
        },
        "additionalProperties": False,
    }

    def obj(properties, required=()):
        return {
            "type": "object",
            "required": list(required),
            "properties": dict(properties),
            "additionalProperties": False,
        }

    matrix = (
        (
            "contacts.search", "directory:read", "read",
            obj({"query": query, "limit": limit}, ("query",)),
            obj(
                {
                    "candidates": {"type": "array", "items": candidate},
                    "partial": {"type": "boolean"},
                },
                ("candidates", "partial"),
            ),
            (), None, "low", "safe",
        ),
        (
            "contacts.resolve", "directory:read", "read",
            obj(
                {"query": query, "channel": channel, "purpose": purpose},
                ("query",),
            ),
            obj(
                {
                    "outcome": {"type": "string"},
                    "candidates": {"type": "array", "items": candidate},
                    "matched_by": {"type": ["string", "null"]},
                    "reason": {"type": ["string", "null"]},
                },
                ("outcome", "candidates", "matched_by", "reason"),
            ),
            (), None, "low", "safe",
        ),
        (
            "contacts.get", "directory:read", "read",
            obj({"contact_id": contact_id}, ("contact_id",)),
            obj({"candidate": candidate}, ("candidate",)),
            (), None, "low", "safe",
        ),
        (
            "contacts.tree.read", "directory:read", "read",
            obj({"branch_id": branch_id}, ()),
            obj(
                {
                    "branches": {"type": "array", "items": {"type": "object"}},
                    "partial": {"type": "boolean"},
                },
                ("branches", "partial"),
            ),
            (), None, "low", "safe",
        ),
        (
            "contacts.list.members", "grouping:read", "read",
            obj({"list_id": list_id}, ("list_id",)),
            obj(
                {
                    "candidates": {"type": "array", "items": candidate},
                    "partial": {"type": "boolean"},
                },
                ("candidates", "partial"),
            ),
            (), None, "low", "safe",
        ),
        (
            "contacts.consent.read", "consent:read", "read",
            obj(
                {"contact_id": contact_id, "channel": channel},
                ("contact_id", "channel"),
            ),
            obj({"axes": {"type": "array", "items": {"type": "object"}}},
                ("axes",)),
            (), None, "low", "safe",
        ),
        (
            "contacts.activity.read", "activity:read", "read",
            obj({"contact_id": contact_id, "limit": limit}, ("contact_id",)),
            obj(
                {
                    "events": {"type": "array", "items": {"type": "object"}},
                    "partial": {"type": "boolean"},
                },
                ("events", "partial"),
            ),
            (), None, "low", "safe",
        ),
        (
            "contacts.segment.preview", "audience:preview", "read",
            obj(
                {
                    "segment_id": segment_id,
                    "channel": channel,
                    "purpose": purpose,
                },
                ("segment_id", "channel", "purpose"),
            ),
            obj(
                {
                    "total": {"type": "integer"},
                    "eligible": {"type": "integer"},
                    "excluded": {"type": "integer"},
                    "exclusion_reasons": {"type": "object"},
                    "redacted": {"type": "boolean"},
                },
                (
                    "total", "eligible", "excluded", "exclusion_reasons",
                    "redacted",
                ),
            ),
            (), None, "low", "safe",
        ),
        (
            "contacts.propose", "proposal:write", "write",
            obj(
                {
                    "display_name": {
                        "type": "string", "minLength": 1, "maxLength": 200,
                    },
                    "primary_branch_id": branch_id,
                    "channel": channel,
                    "address_capture_ref": {
                        "type": "string", "pattern": ADDRESS_CAPTURE_PATTERN,
                    },
                    "note": {"type": "string", "maxLength": 500},
                },
                (
                    "display_name", "primary_branch_id", "channel",
                    "address_capture_ref",
                ),
            ),
            receipt,
            (
                "display_name", "primary_branch_id", "channel",
                "address_capture_ref",
            ),
            "contacts.proposal", "medium", "reconcile",
        ),
        (
            "contacts.update.propose", "proposal:write", "write",
            obj(
                {
                    "contact_id": contact_id,
                    "record_version": {
                        "type": "string", "minLength": 8, "maxLength": 64,
                    },
                    "changes": {"type": "object"},
                },
                ("contact_id", "record_version", "changes"),
            ),
            receipt,
            ("contact_id", "record_version", "changes"),
            "contacts.proposal", "medium", "reconcile",
        ),
        (
            "contacts.list.add", "grouping:write", "write",
            obj(
                {"list_id": list_id, "contact_id": contact_id},
                ("list_id", "contact_id"),
            ),
            grouping_receipt,
            ("list_id", "contact_id"),
            "contacts.grouping", "low", "idempotent",
        ),
        (
            "contacts.tag.apply", "grouping:write", "write",
            obj(
                {"tag_id": tag_id, "contact_id": contact_id},
                ("tag_id", "contact_id"),
            ),
            grouping_receipt,
            ("tag_id", "contact_id"),
            "contacts.grouping", "low", "idempotent",
        ),
    )
    definitions = []
    for (
        capability_id, family, effect, input_schema, output_schema,
        preview_fields, verifier, risk, retry_policy,
    ) in matrix:
        name, _separator, action = family.partition(":")
        definitions.append(TrustedCapabilityDefinition(
            capability_id=capability_id,
            version="1.0.0",
            provider=CONTACTS_PROVIDER,
            input_schema=input_schema,
            output_schema=output_schema,
            required_scopes=frozenset({
                synthetic_scope(CONTACTS_PROVIDER, name, action)
            }),
            effect=effect,
            risk=risk,
            retry_policy=retry_policy,
            preview_fields=preview_fields,
            verifier=verifier,
            # There is no consenting person and no installation, only the
            # tenant's own account -- the same shape U3 introduced for a
            # provider authenticated by an account rather than by a grant.
            authority_profile="account",
        ))
    return tuple(definitions)


def build_contacts_runtime(executor, connector=None):
    """Register the contacts store as a provider runtime like any other."""
    return ProviderRuntime(
        provider=CONTACTS_PROVIDER,
        connector=connector or FirstPartyStore(CONTACTS_PROVIDER),
        executor=executor,
        definitions=contacts_definitions(),
        credential_strategy=FIRST_PARTY_STORE_CREDENTIAL,
    )


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
    ProviderRegistration(
        provider=CONTACTS_PROVIDER,
        definitions=contacts_definitions,
        # No secret, so nothing to exchange and nothing to refresh. Asking for
        # provider authority here is an error rather than a no-op.
        credential_strategy=FIRST_PARTY_STORE_CREDENTIAL,
        manifest_version="contacts.operations.v1",
    ),
    ProviderRegistration(
        provider=TWILIO_PROVIDER,
        definitions=twilio_definitions,
        credential_strategy=STATIC_ACCOUNT_CREDENTIAL,
        manifest_version="twilio.operations.v1",
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
