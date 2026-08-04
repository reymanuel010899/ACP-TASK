import json
from dataclasses import replace
from pathlib import Path

import pytest

from agents.orchestrator.slack_operations import (
    MANIFEST_VERSION,
    SlackOperationManifestError,
    load_slack_operations,
)
from libs.integrations.catalog import slack_definitions


MANIFEST = Path(__file__).parents[2] / "config" / "slack_operations_v1.yaml"


def _keys(value):
    if isinstance(value, dict):
        return set(value).union(*(_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_keys(item) for item in value), set())
    return set()


def _manifest(tmp_path, mutate):
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    mutate(payload)
    target = tmp_path / "slack-operations.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def test_v1_manifest_is_exact_and_separates_conversation_from_authority():
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert payload["manifest_version"] == MANIFEST_VERSION == "slack.operations.v1"
    assert set(payload["method_coverage"]) == {
        "supported", "conditional", "excluded",
    }
    assert all(
        item["prerequisites"]
        for status in payload["method_coverage"].values()
        for item in status
    )
    operation_keys = _keys(payload["operations"])
    for trusted_only_field in (
        "input_schema", "output_schema", "required_scopes", "effect", "risk",
        "retry_policy", "verifier", "rollout_version",
    ):
        assert trusted_only_field not in operation_keys

    runtime_recipes = {
        step["capability_id"]
        for operation in payload["operations"]
        for step in operation["capability_recipe"]
    }
    assert runtime_recipes == {
        definition.capability_id for definition in slack_definitions()
    } - {"slack.file.upload"}
    assert next(
        operation for operation in payload["operations"]
        if operation["operation_id"] == "slack.connection.status"
    )["capability_recipe"] == []

    future = {
        item["method"]: item["state"]
        for item in payload["method_coverage"]["conditional"]
        if item["state"] != "runtime"
    }
    # Promoted by U5: reactions.remove is a runtime descriptor now, so it
    # must have left the future set entirely.
    assert "reactions.remove" not in future
    assert {
        item["method"] for item in payload["method_coverage"]["conditional"]
        if item["state"] == "runtime"
    } >= {"reactions.remove"}
    assert "pins.add" not in future
    assert "pins.remove" not in future
    assert "bookmarks.add" not in future
    assert future["bookmarks.edit"] == "planned"
    assert future["conversations.create"] == "planned"
    # Promoted by U6 slice B: search runs, but only as a user profile.
    assert "search.messages" not in future
    assert future["files.getUploadURLExternal"] == "dormant"
    assert future["canvases.create"] == "dormant"
    assert future["chat.delete"] == "dormant"


def test_local_connection_status_projects_without_executable_authority():
    registry = load_slack_operations(slack_definitions(), MANIFEST)

    projection = registry.model_projection(
        set(), {"slack_connection_status": True},
    )

    assert projection == ({
        "operation_id": "slack.connection.status",
        "operation_kind": "local",
        "availability": "supported",
        "aliases": [
            "slack status", "is slack connected", "estado de slack",
            "slack está conectado",
        ],
        "slots": [],
        "prerequisites": ["tenant_context"],
        "recovery": {"unavailable": "explain_installation_state"},
        "presentation": {
            "kind": "connection_status", "label": "Slack connection",
        },
    },)


def test_join_projects_only_installed_family_enabled_and_policy_visible_operations():
    registry = load_slack_operations(slack_definitions(), MANIFEST)
    installed = {
        "slack.channels.list", "slack.conversation.read", "slack.message.send",
    }
    families = {
        "slack_channel_discovery": True,
        "slack_conversation_reads": True,
        "slack_messaging": True,
    }

    projection = registry.model_projection(
        installed, families,
        policy_visible=lambda operation: operation.operation_id != "slack.message.send",
    )

    assert [item["operation_id"] for item in projection] == [
        "slack.channels.list", "slack.conversation.read",
        "slack.conversation.summarize",
    ]
    assert "capability_recipe" not in json.dumps(projection)
    assert "required_scopes" not in json.dumps(projection)

    resolved = registry.resolve_visible(installed, families)
    send = next(
        item for item in resolved
        if item.descriptor.operation_id == "slack.message.send"
    )
    assert send.trusted_capabilities[0].effect == "write"
    assert send.trusted_capabilities[0].required_scopes == frozenset({"chat:write"})


def test_disabling_one_family_does_not_change_unrelated_operations():
    registry = load_slack_operations(slack_definitions(), MANIFEST)
    installed = {definition.capability_id for definition in slack_definitions()}
    enabled = {family: True for family in registry.family_flags}

    before = registry.model_projection(installed, enabled)
    enabled["slack_messaging"] = False
    after = registry.model_projection(installed, enabled)

    removed = {item["operation_id"] for item in before} - {
        item["operation_id"] for item in after
    }
    assert removed == {"slack.message.send", "slack.thread.reply"}
    assert "slack.channels.list" in {item["operation_id"] for item in after}


def test_join_fails_closed_for_missing_or_incompatible_capability(tmp_path):
    missing = tuple(
        definition for definition in slack_definitions()
        if definition.capability_id != "slack.message.send"
    )
    with pytest.raises(SlackOperationManifestError, match="not trusted"):
        load_slack_operations(missing, MANIFEST)

    incompatible = tuple(
        replace(definition, provider="google")
        if definition.capability_id == "slack.message.send" else definition
        for definition in slack_definitions()
    )
    with pytest.raises(SlackOperationManifestError, match="provider"):
        load_slack_operations(incompatible, MANIFEST)

    drifted_schema = tuple(
        replace(definition, input_schema={
            "type": "object", "required": ["channel_id", "blocks"],
            "properties": {
                "channel_id": {"type": "string"},
                "blocks": {"type": "array"},
            },
            "additionalProperties": False,
        }) if definition.capability_id == "slack.message.send" else definition
        for definition in slack_definitions()
    )
    with pytest.raises(SlackOperationManifestError, match="trusted capability schema"):
        load_slack_operations(drifted_schema, MANIFEST)


def test_wrong_manifest_version_and_unregistered_installs_fail_closed(tmp_path):
    wrong_version = _manifest(
        tmp_path, lambda payload: payload.update(manifest_version="slack.operations.v2"),
    )
    with pytest.raises(SlackOperationManifestError, match="manifest version"):
        load_slack_operations(slack_definitions(), wrong_version)

    registry = load_slack_operations(slack_definitions(), MANIFEST)
    with pytest.raises(SlackOperationManifestError, match="installed capability"):
        registry.model_projection(
            {"slack.channels.list", "slack.fabricated.write"},
            {"slack_channel_discovery": True},
        )


def test_alias_lookup_is_deterministic_for_available_and_unavailable_operations():
    registry = load_slack_operations(slack_definitions(), MANIFEST)

    assert registry.lookup_alias("please post message for the team").operation_id == (
        "slack.message.send"
    )
    assert registry.lookup_alias("necesito listar canales privados").operation_id == (
        "slack.private_channels.list"
    )
    assert registry.lookup_alias("do something mysterious") is None


def test_scope_bundles_group_by_family_and_carry_every_needed_scope():
    definitions = slack_definitions()
    bundles = load_slack_operations(definitions).scope_bundles(definitions)

    assert bundles["slack_pins"]["scopes"] == ["pins:write"]
    assert bundles["slack_pins"]["operations"] == [
        "slack.message.pin", "slack.message.unpin",
    ]
    # The DM family carries both scopes its executor uses, so granting the
    # bundle cannot produce a connection that fails at Slack.
    assert bundles["slack_direct_messages"]["scopes"] == [
        "chat:write", "im:write",
    ]
    assert "slack.connection.status" not in {
        operation
        for bundle in bundles.values()
        for operation in bundle["operations"]
    }


def test_missing_bundles_name_only_what_a_connection_cannot_run():
    definitions = slack_definitions()
    registry = load_slack_operations(definitions)
    granted = ["channels:read", "channels:history", "chat:write", "users:read"]

    missing = registry.missing_scope_bundles(definitions, granted)
    families = {bundle["family"]: bundle for bundle in missing}

    assert "slack_messaging" not in families
    assert "slack_conversation_reads" not in families
    assert families["slack_pins"]["missing_scopes"] == ["pins:write"]
    assert families["slack_direct_messages"]["missing_scopes"] == ["im:write"]
    # Already-granted scopes are not re-requested, so the prompt stays minimal.
    assert "chat:write" not in families["slack_direct_messages"]["missing_scopes"]


def test_asking_for_one_family_does_not_drag_in_the_others():
    definitions = slack_definitions()
    registry = load_slack_operations(definitions)

    missing = registry.missing_scope_bundles(
        definitions, ["channels:read"], families=["slack_pins"],
    )

    assert [bundle["family"] for bundle in missing] == ["slack_pins"]


def test_a_fully_granted_family_asks_for_nothing():
    definitions = slack_definitions()
    registry = load_slack_operations(definitions)

    assert registry.missing_scope_bundles(
        definitions, ["pins:write"], families=["slack_pins"],
    ) == []
