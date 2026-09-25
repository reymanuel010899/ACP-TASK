from dataclasses import replace

import jsonschema
import pytest

from libs.integrations.catalog import (
    REFRESHED_OAUTH_CREDENTIAL,
    SEALED_TOKEN_DOCUMENT_CREDENTIAL,
    STATIC_ACCOUNT_CREDENTIAL,
    CapabilityUnavailable,
    ConnectionCapabilitySnapshot,
    ExternalAgentOffer,
    ProviderRuntime,
    ProviderRuntimeRegistry,
    TrustedCapabilityDefinition,
    contacts_definitions,
    credential_strategy_for,
    google_definitions,
    provider_definitions,
    registered_providers,
    slack_definitions,
    twilio_definitions,
)


class FakeConnector:
    pass


class FakeExecutor:
    pass


def _definition():
    return TrustedCapabilityDefinition(
        capability_id="synthetic.item.read",
        version="1.0.0",
        provider="synthetic",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        required_scopes=frozenset({"items:read"}),
        effect="read",
        risk="low",
        retry_policy="safe",
        preview_fields=(),
        verifier="synthetic.item",
    )


def _snapshot():
    return ConnectionCapabilitySnapshot(
        connection_id="conn:1",
        tenant_id="org:acme",
        capability_id="synthetic.item.read",
        capability_version="1.0.0",
        credential_version=2,
        effective_scopes=frozenset({"items:read"}),
        health="healthy",
        rollout_version="rollout-1",
    )


def test_trusted_runtime_resolves_from_definition_and_snapshot():
    definition = _definition()
    runtime = ProviderRuntime(
        provider="synthetic",
        connector=FakeConnector(),
        executor=FakeExecutor(),
        definitions=(definition,),
    )
    registry = ProviderRuntimeRegistry((runtime,))

    binding = registry.resolve(_snapshot(), expected_rollout="rollout-1")

    assert binding.definition is definition
    assert binding.executor is runtime.executor
    assert binding.connector is runtime.connector


@pytest.mark.parametrize(
    "snapshot",
    [
        replace(_snapshot(), capability_version="2.0.0"),
        replace(_snapshot(), effective_scopes=frozenset()),
        replace(_snapshot(), health="degraded"),
        replace(_snapshot(), rollout_version="old"),
    ],
)
def test_stale_or_unauthorized_snapshot_is_rejected(snapshot):
    registry = ProviderRuntimeRegistry((ProviderRuntime(
        provider="synthetic",
        connector=FakeConnector(),
        executor=FakeExecutor(),
        definitions=(_definition(),),
    ),))

    with pytest.raises(CapabilityUnavailable):
        registry.resolve(snapshot, expected_rollout="rollout-1")


def test_external_offer_cannot_be_registered_as_native_runtime():
    offer = ExternalAgentOffer(
        offer_id="offer:1",
        agent_principal_id="agent:untrusted",
        capability_id="synthetic.item.read",
        capability_version="1.0.0",
    )
    registry = ProviderRuntimeRegistry()

    with pytest.raises(TypeError):
        registry.register(offer)


def test_slack_private_capabilities_require_private_channel_scopes():
    definitions = {
        definition.capability_id: definition
        for definition in slack_definitions()
    }

    assert definitions["slack.channels.list"].required_scopes == frozenset({
        "channels:read"
    })
    assert definitions["slack.private_channels.list"].required_scopes == frozenset({
        "groups:read"
    })
    assert definitions["slack.private_conversation.read"].required_scopes == frozenset({
        "groups:history"
    })
    assert definitions["slack.private_thread.read"].required_scopes == frozenset({
        "groups:history"
    })


def test_slack_conversation_primitives_have_narrow_scopes_and_inputs():
    definitions = {
        definition.capability_id: definition for definition in slack_definitions()
    }
    assert definitions["slack.users.list"].required_scopes == frozenset({"users:read"})
    assert definitions["slack.message.permalink"].required_scopes == frozenset({"channels:history"})
    # conversations.open then chat.postMessage: both scopes, or the check
    # passes and Slack refuses.
    assert definitions["slack.direct_message.send"].required_scopes == frozenset(
        {"im:write", "chat:write"}
    )
    assert definitions["slack.direct_message.send"].effect == "write"
    assert definitions["slack.direct_message.send"].preview_fields == ("user_id", "text")
    history = definitions["slack.conversation.read"].input_schema["properties"]
    assert {"oldest", "latest", "cursor", "limit"}.issubset(history)


def test_slack_capabilities_declare_allowlisted_output_fields():
    definitions = {
        definition.capability_id: definition for definition in slack_definitions()
    }
    expected_fields = {
        "slack.channels.list": {"channels", "next_cursor", "partial"},
        "slack.private_channels.list": {"channels", "next_cursor", "partial"},
        "slack.conversation.read": {"messages", "next_cursor", "partial"},
        "slack.private_conversation.read": {"messages", "next_cursor", "partial"},
        "slack.thread.read": {"messages", "next_cursor", "partial"},
        "slack.private_thread.read": {"messages", "next_cursor", "partial"},
        "slack.users.list": {"users", "next_cursor", "partial"},
        "slack.message.permalink": {"channel_id", "message_ts", "permalink"},
        "slack.message.send": {
            "provider", "capability_id", "provider_id", "team_id",
            "channel_id", "message_ts",
        },
        "slack.thread.reply": {
            "provider", "capability_id", "provider_id", "team_id",
            "channel_id", "message_ts",
        },
        "slack.direct_message.send": {
            "provider", "capability_id", "provider_id", "team_id",
            "channel_id", "message_ts", "user_id",
        },
        "slack.reaction.add": {
            "provider", "capability_id", "provider_id", "team_id",
            "channel_id", "message_ts", "reaction",
        },
        "slack.reaction.remove": {
            "provider", "capability_id", "provider_id", "team_id",
            "channel_id", "message_ts", "reaction",
        },
        "slack.message.pin": {
            "provider", "capability_id", "provider_id", "team_id",
            "channel_id", "message_ts",
        },
        "slack.message.unpin": {
            "provider", "capability_id", "provider_id", "team_id",
            "channel_id", "message_ts",
        },
        "slack.search.messages": {"messages", "next_cursor", "partial"},
        "slack.channel.create": {
            "provider", "capability_id", "provider_id", "team_id",
            "channel_id", "name",
        },
        "slack.channel.rename": {
            "provider", "capability_id", "provider_id", "team_id",
            "channel_id", "name",
        },
        "slack.channel.set_topic": {
            "provider", "capability_id", "provider_id", "team_id",
            "channel_id", "topic",
        },
        "slack.channel.archive": {
            "provider", "capability_id", "provider_id", "team_id",
            "channel_id",
        },
        "slack.channel.invite": {
            "provider", "capability_id", "provider_id", "team_id",
            "channel_id", "invited",
        },
        "slack.bookmark.add": {
            "provider", "capability_id", "provider_id", "team_id",
            "channel_id", "bookmark_id", "title",
        },
        "slack.file.upload": {
            "provider", "capability_id", "provider_id", "team_id",
            "channel_id", "file_id",
        },
    }

    assert set(definitions) == set(expected_fields)
    for capability_id, fields in expected_fields.items():
        schema = definitions[capability_id].output_schema
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert set(schema["properties"]) == fields
        jsonschema.Draft202012Validator.check_schema(schema)


def test_every_provider_is_registered_in_exactly_one_place():
    """A composition site asks the registry, never a hardcoded pair."""
    # "contacts" is first-party and has no external service behind it, but it
    # is registered here like any other provider: the registry is what makes a
    # capability executable, and carving an exception into it would grow a
    # second authority join.
    assert set(registered_providers()) == {"google", "slack", "contacts", "twilio"}
    assert provider_definitions() == (
        google_definitions() + slack_definitions() + contacts_definitions()
        + twilio_definitions()
    )
    assert provider_definitions("contacts") == contacts_definitions()
    assert provider_definitions("slack") == slack_definitions()
    assert provider_definitions("google") == google_definitions()
    assert provider_definitions("twilio") == twilio_definitions()
    assert {
        definition.provider for definition in provider_definitions()
    } == set(registered_providers())


def test_an_unregistered_provider_yields_nothing_rather_than_a_default():
    with pytest.raises(CapabilityUnavailable):
        provider_definitions("unregistered")
    with pytest.raises(CapabilityUnavailable):
        credential_strategy_for("unregistered")


def test_a_providers_credential_shape_is_declared_not_branched_on():
    assert credential_strategy_for("google") is REFRESHED_OAUTH_CREDENTIAL
    assert credential_strategy_for("slack") is SEALED_TOKEN_DOCUMENT_CREDENTIAL
    assert credential_strategy_for("twilio") is STATIC_ACCOUNT_CREDENTIAL


def test_a_sealed_document_is_read_as_authority_without_a_refresh_exchange():
    authority = SEALED_TOKEN_DOCUMENT_CREDENTIAL.authority(
        b'{"access_token": "xoxb-1", "granted_scopes": ["chat:write"]}',
        connector=None,
    )

    assert authority.access_token == "xoxb-1"
    assert authority.granted_scopes == frozenset({"chat:write"})


@pytest.mark.parametrize("secret", [
    b"not json",
    b"[]",
    b'{"access_token": ""}',
    b'{"granted_scopes": ["chat:write"]}',
    b"\xff\xfe",
])
def test_an_unusable_sealed_document_denies_rather_than_dispatching(secret):
    with pytest.raises(PermissionError):
        SEALED_TOKEN_DOCUMENT_CREDENTIAL.authority(secret, connector=None)


def test_a_refresh_credential_exchanges_the_sealed_token_for_authority():
    class Refreshed:
        access_token = "ya29.short-lived"
        granted_scopes = frozenset({"https://www.googleapis.com/auth/gmail.send"})

    class RefreshingConnector:
        def __init__(self):
            self.seen = []

        def refresh(self, refresh_token):
            self.seen.append(refresh_token)
            return Refreshed()

    connector = RefreshingConnector()
    authority = REFRESHED_OAUTH_CREDENTIAL.authority(b"sealed-refresh", connector)

    assert connector.seen == ["sealed-refresh"]
    assert authority.access_token == "ya29.short-lived"
    assert authority.granted_scopes == Refreshed.granted_scopes

    with pytest.raises(PermissionError):
        REFRESHED_OAUTH_CREDENTIAL.authority(b"sealed-refresh", None)


def test_a_runtime_carries_its_credential_strategy_into_the_binding():
    runtime = ProviderRuntime(
        provider="synthetic",
        connector=FakeConnector(),
        executor=FakeExecutor(),
        definitions=(_definition(),),
        credential_strategy=SEALED_TOKEN_DOCUMENT_CREDENTIAL,
    )

    binding = ProviderRuntimeRegistry((runtime,)).resolve(
        _snapshot(), expected_rollout="rollout-1",
    )

    assert binding.credential_strategy is SEALED_TOKEN_DOCUMENT_CREDENTIAL


def test_an_untrusted_credential_strategy_cannot_be_registered():
    with pytest.raises(TypeError):
        ProviderRuntime(
            provider="synthetic",
            connector=FakeConnector(),
            executor=FakeExecutor(),
            definitions=(_definition(),),
            credential_strategy=lambda secret, connector=None: secret,
        )
