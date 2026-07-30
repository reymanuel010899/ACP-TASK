from dataclasses import replace

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
