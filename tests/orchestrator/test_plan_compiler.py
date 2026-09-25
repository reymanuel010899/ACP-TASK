import pytest

from agents.orchestrator.planner import PlanCompiler, PlanRejected, descriptor_hash
from libs.integrations.catalog import ConnectionCapabilitySnapshot, TrustedCapabilityDefinition


def definition(
    capability_id, provider="synthetic", effect="read", input_schema=None,
    output=None,
):
    return TrustedCapabilityDefinition(
        capability_id=capability_id, version="1.0.0", provider=provider,
        input_schema=input_schema or {"type": "object", "additionalProperties": True},
        output_schema=output or {"type": "object", "additionalProperties": True},
        required_scopes=frozenset({"scope"}), effect=effect, risk="low",
        retry_policy="safe", preview_fields=("payload",) if effect == "write" else (),
        verifier=None,
    )


def snapshot(capability_id, connection_id="conn:1"):
    return ConnectionCapabilitySnapshot(
        connection_id=connection_id, tenant_id="org:acme",
        capability_id=capability_id, capability_version="1.0.0",
        credential_version=1, effective_scopes=frozenset({"scope"}),
        health="healthy", rollout_version="rollout-1",
    )


def step(capability, step_id="step-1", depends_on=None, input_value=None):
    item = definition(capability)
    return {
        "step_id": step_id, "capability_id": capability,
        "capability_version": "1.0.0", "connection_id": "conn:1",
        "descriptor_snapshot_hash": descriptor_hash(item),
        "input": input_value or {}, "depends_on": depends_on or [],
    }


def test_rejects_invented_capability_cycle_and_eleventh_step():
    known = definition("known.read")
    compiler = PlanCompiler([known], [snapshot("known.read")], "rollout-1")
    with pytest.raises(PlanRejected, match="not catalogued"):
        compiler.compile({"tenant_id": "org:acme", "goal": "x", "steps": [
            {**step("known.read"), "capability_id": "invented.write"},
        ]})

    cyclic = [step("known.read", "a", ["b"]), step("known.read", "b", ["a"])]
    with pytest.raises(PlanRejected, match="cyclic"):
        compiler.compile({"tenant_id": "org:acme", "goal": "x", "steps": cyclic})

    too_many = [step("known.read", "s%02d" % number, [] if number == 0 else ["s%02d" % (number - 1)]) for number in range(11)]
    with pytest.raises(PlanRejected, match="ten steps"):
        compiler.compile({"tenant_id": "org:acme", "goal": "x", "steps": too_many})


def test_rejects_stale_descriptor_and_unauthorized_connection():
    known = definition("known.read")
    compiler = PlanCompiler([known], [snapshot("known.read")], "rollout-1")
    with pytest.raises(PlanRejected, match="descriptor"):
        compiler.compile({"tenant_id": "org:acme", "goal": "x", "steps": [
            {**step("known.read"), "descriptor_snapshot_hash": "stale"},
        ]})
    with pytest.raises(PlanRejected, match="connection"):
        compiler.compile({"tenant_id": "org:acme", "goal": "x", "steps": [
            {**step("known.read"), "connection_id": "conn:other"},
        ]})


def test_cross_provider_output_reference_creates_compiler_owned_disclosure():
    source = definition("source.read", provider="slack", output={
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "additionalProperties": False,
    })
    sink = definition(
        "sink.write", provider="google", effect="write",
        input_schema={
            "type": "object",
            "properties": {"body": {"type": "string"}},
            "additionalProperties": False,
        },
    )
    compiler = PlanCompiler(
        [source, sink],
        [snapshot("source.read", "conn:s"), snapshot("sink.write", "conn:g")],
        "rollout-1",
    )
    source_step = {
        **step("source.read", "read"),
        "connection_id": "conn:s",
        "descriptor_snapshot_hash": descriptor_hash(source),
    }
    sink_step = {
        **step("sink.write", "send", ["read"], {"body": {"$ref": "read.output.summary"}}),
        "connection_id": "conn:g",
        "descriptor_snapshot_hash": descriptor_hash(sink),
    }
    result = compiler.compile({"tenant_id": "org:acme", "goal": "x", "steps": [source_step, sink_step]})
    assert result["disclosures"] == [{
        "step_id": "send", "source_step_id": "read", "source": "slack",
        "destination": "google", "classification": "provider_data",
        "reference": "read.output.summary",
    }]
