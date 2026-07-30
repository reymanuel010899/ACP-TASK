import pytest

from agents.provider.agent import ProviderAgent, RpcError
from agents.provider.config import PricingConfig
from agents.orchestrator.tools import validate_provider_input
from libs.protocol import (
    TASK_NEEDS_INPUT,
    collaboration_envelope,
    validate_collaboration_envelope,
)


def _provider(tmp_path):
    return ProviderAgent(
        base_url="http://provider.test",
        verification_url="http://verification.test",
        keys_dir=str(tmp_path),
        pricing=PricingConfig(),
    )


def test_native_provider_accepts_explicit_single_capability(tmp_path):
    provider = _provider(tmp_path)
    offer = provider.handle_payload({
        "type": "task.request",
        "capability_id": "terraform.generate",
        "conversation_id": "conv-1",
        "input": {"containers": 1, "load_balancer": "alb"},
    })
    assert offer["capability_id"] == "terraform.generate"


def test_native_provider_rejects_unknown_capability(tmp_path):
    provider = _provider(tmp_path)
    with pytest.raises(RpcError, match="unsupported capability"):
        provider.handle_payload({
            "type": "task.request",
            "capability_id": "calendar.create",
            "input": {"containers": 1, "load_balancer": "alb"},
        })


def test_collaboration_envelopes_require_stable_task_and_schema():
    need = collaboration_envelope(
        TASK_NEEDS_INPUT,
        "task-1",
        "conv-1",
        "A start time is required.",
        missing_fields=["start"],
        input_schema={"type": "object", "required": ["start"]},
    )
    assert validate_collaboration_envelope(need) == need

    with pytest.raises(ValueError, match="missing_fields"):
        collaboration_envelope(
            TASK_NEEDS_INPUT,
            "task-1",
            "conv-1",
            "Missing.",
            input_schema={"type": "object"},
        )


def test_orchestrator_requires_discovered_capability_schema():
    candidate = {
        "id": "agent:calendar",
        "input_schema": {
            "type": "object",
            "required": ["title"],
            "properties": {"title": {"type": "string"}},
        },
    }
    validate_provider_input(candidate, "calendar.create", {"title": "Interview"})

    with pytest.raises(ValueError, match="title"):
        validate_provider_input(candidate, "calendar.create", {})
    with pytest.raises(ValueError, match="does not publish"):
        validate_provider_input(
            {"id": "agent:legacy"}, "calendar.create", {"title": "Interview"}
        )
