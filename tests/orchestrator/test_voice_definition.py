import pytest

from agents.orchestrator.voice_definition import VoiceDefinition


def definition(**overrides):
    values = {
        "persona_id": "support", "persona_version": "3",
        "model": "grok-voice-2026-06-15", "voice": "eve",
        "opening_script": "Hola, llamo de Acme.",
        "topic_policy_id": "support-public", "topic_policy_version": "7",
        "maximum_duration_seconds": 300,
        "transfer_policy_id": "support-hours", "transfer_policy_version": "4",
        "recording": False,
    }
    values.update(overrides)
    return VoiceDefinition.from_mapping(values)


def test_every_approved_voice_field_changes_the_hash():
    original = definition()
    for field, changed in {
        "persona_id": "sales", "persona_version": "4", "model": "grok-voice-2026-07-01",
        "voice": "ara", "opening_script": "Hello", "topic_policy_id": "public-v2",
        "topic_policy_version": "8", "maximum_duration_seconds": 301,
        "transfer_policy_id": "after-hours", "transfer_policy_version": "5",
        "recording": True,
    }.items():
        assert definition(**{field: changed}).digest != original.digest


def test_voice_definition_rejects_alias_models_and_destinations():
    with pytest.raises(ValueError, match="pinned"):
        definition(model="grok-voice-latest")
    with pytest.raises(ValueError, match="destination"):
        VoiceDefinition.from_mapping(dict(definition().as_dict(), to="+15551234567"))

