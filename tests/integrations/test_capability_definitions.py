from dataclasses import replace

import jsonschema
import pytest

from libs.integrations.catalog import (
    CapabilityUnavailable,
    ConnectionCapabilitySnapshot,
    ExternalAgentOffer,
    ProviderRuntime,
    ProviderRuntimeRegistry,
    TrustedCapabilityDefinition,
    slack_definitions,
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
