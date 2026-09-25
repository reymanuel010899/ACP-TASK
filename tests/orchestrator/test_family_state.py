"""Capability families are durable, per-tenant, and independently switchable."""

from agents.orchestrator.dynamic_workflow_service import DynamicWorkflowService
from agents.orchestrator.slack_operations import load_slack_operations
from libs.integrations.catalog import slack_definitions
from libs.integrations.control_plane import (
    EMERGENCY_STOP,
    FAMILY_DISABLED,
    UNAVAILABLE,
    TenantControlPlane,
    build_tenant_control_plane,
    capability_effect_resolver,
    capability_family_resolver,
)
from services.oauth.repository import OAuthRepository


TENANT = "org:acme"
OTHER_TENANT = "org:beta"


class _UnreadableStore:
    def control_plane_state(self, tenant_id):
        raise RuntimeError("control plane is down")


class _SlackConnections:
    def list_tenant_installations(self, tenant, provider):
        return [{
            "connection_id": "conn:s", "team_id": "T1", "team_name": "Acme",
            "status": "connected", "credential_version": 1,
            "granted_scopes": ["chat:write", "channels:read"],
            "enabled_capabilities": [
                "slack.message.send", "slack.channels.list",
            ],
        }]


def _repository(tmp_path, name="control-plane.db"):
    return OAuthRepository(str(tmp_path / name))


def _control_plane(store):
    return build_tenant_control_plane(store, slack_definitions())


def test_disabling_one_family_leaves_every_other_family_alone(tmp_path):
    repository = _repository(tmp_path)
    for family in ("slack_messaging", "slack_direct_messages"):
        repository.set_capability_family_enabled(TENANT, family, True, 100)

    repository.set_capability_family_enabled(
        TENANT, "slack_direct_messages", False, 200,
    )

    state = repository.control_plane_state(TENANT)
    assert state["families"]["slack_messaging"] is True
    assert state["families"]["slack_direct_messages"] is False


def test_one_tenants_family_switch_never_reaches_another_tenant(tmp_path):
    repository = _repository(tmp_path)
    repository.set_capability_family_enabled(TENANT, "slack_messaging", True, 100)
    repository.set_capability_family_enabled(
        OTHER_TENANT, "slack_messaging", True, 100,
    )

    repository.set_capability_family_enabled(TENANT, "slack_messaging", False, 200)

    assert repository.control_plane_state(TENANT)["families"] == {
        "slack_messaging": False
    }
    assert repository.control_plane_state(OTHER_TENANT)["families"] == {
        "slack_messaging": True
    }


def test_a_family_nobody_enabled_is_off_rather_than_assumed_on(tmp_path):
    repository = _repository(tmp_path)

    plane = _control_plane(repository)

    assert plane.family_flags(TENANT) == {}
    decision = plane.decide(
        TENANT, capability_id="slack.message.send", effect="write",
    )
    assert not decision
    assert decision.reason.startswith(FAMILY_DISABLED)


def test_a_disabled_family_blocks_its_writes_and_says_which_family(tmp_path):
    repository = _repository(tmp_path)
    repository.set_capability_family_enabled(TENANT, "slack_messaging", False, 100)
    plane = _control_plane(repository)

    decision = plane.decide(
        TENANT, capability_id="slack.message.send", effect="write",
    )

    assert decision.reason == "%s:slack_messaging" % FAMILY_DISABLED


def test_a_disabled_family_still_permits_the_reconciliation_read(tmp_path):
    repository = _repository(tmp_path)
    repository.set_capability_family_enabled(TENANT, "slack_messaging", False, 100)
    plane = _control_plane(repository)

    # The unknown outcome of a write in this family can only be resolved by
    # reading the very API the disable removed. Gating the read would strand
    # the effect permanently, so the disable is write-only by construction.
    assert plane.decide(
        TENANT, capability_id="slack.conversation.read", effect="read",
    )
    assert plane.decide(
        TENANT, capability_id="slack.message.send", effect="write",
        purpose="recovery",
    )


def test_family_state_survives_a_process_restart_with_no_environment_change(
    tmp_path,
):
    path = str(tmp_path / "restart.db")
    first = OAuthRepository(path)
    first.set_capability_family_enabled(TENANT, "slack_messaging", True, 100)
    first.set_capability_family_enabled(
        TENANT, "slack_direct_messages", False, 100,
    )
    first.close()

    # A second process, same disk, no environment variables involved.
    second = OAuthRepository(path)

    assert second.control_plane_state(TENANT)["families"] == {
        "slack_direct_messages": False, "slack_messaging": True,
    }


def test_an_unreadable_control_plane_denies_writes_rather_than_opening_them():
    plane = TenantControlPlane(_UnreadableStore())

    decision = plane.decide(TENANT, capability_id="slack.message.send")

    assert not decision
    assert decision.reason == UNAVAILABLE


def test_a_stopped_account_reports_every_family_as_off(tmp_path):
    repository = _repository(tmp_path)
    repository.set_capability_family_enabled(TENANT, "slack_messaging", True, 100)
    repository.set_emergency_stop(
        TENANT, True, 200, reason="paged", acting_principal_id="user:ana",
    )
    plane = _control_plane(repository)

    # The projection is what the model is allowed to see. Leaving a family
    # visible during a stop would have the Concierge plan work it can never
    # dispatch, and then explain the refusal afterwards.
    assert plane.family_flags(TENANT) == {"slack_messaging": False}


def test_the_capability_family_map_comes_from_the_operation_manifest():
    registry = load_slack_operations(slack_definitions())

    resolve = capability_family_resolver(registry)

    assert "slack_messaging" in resolve("slack.message.send")
    assert "slack_direct_messages" in resolve("slack.direct_message.send")
    assert resolve("slack.nonexistent") == ()


def test_effects_the_catalog_does_not_know_are_treated_as_writes():
    plane = TenantControlPlane(
        _UnreadableStore(),
        effect_resolver=capability_effect_resolver(slack_definitions()),
    )

    # Guessing "read" for an unrecognised capability would let it walk
    # straight through an emergency stop.
    assert not plane.decide(TENANT, capability_id="slack.unknown.thing")


def test_the_service_prefers_durable_state_over_its_constructor_defaults(
    tmp_path,
):
    repository = _repository(tmp_path)
    repository.set_capability_family_enabled(TENANT, "slack_messaging", True, 100)
    service = DynamicWorkflowService(
        object(), slack_definitions(), _SlackConnections(), object(),
        # These say every family is on. Durable per-tenant state says only one
        # is, and per-tenant state is what a restart cannot change back.
        conversational_reads_enabled=True, slack_writes_enabled=True,
        slack_dms_enabled=True,
        control_plane=_control_plane(repository),
    )

    families = service._slack_family_state(TENANT)

    assert families == {"slack_messaging": True}
    assert service._runtime_slack_operation_ids(TENANT) == frozenset({
        "slack.message.send", "slack.thread.reply",
    })


def test_two_tenants_on_one_process_hold_different_family_answers(tmp_path):
    repository = _repository(tmp_path)
    repository.set_capability_family_enabled(TENANT, "slack_messaging", True, 100)
    repository.set_capability_family_enabled(
        OTHER_TENANT, "slack_messaging", False, 100,
    )
    service = DynamicWorkflowService(
        object(), slack_definitions(), _SlackConnections(), object(),
        control_plane=_control_plane(repository),
    )

    assert service._slack_family_state(TENANT)["slack_messaging"] is True
    assert service._slack_family_state(OTHER_TENANT)["slack_messaging"] is False


def test_a_family_change_takes_effect_without_restarting_anything(tmp_path):
    repository = _repository(tmp_path)
    plane = _control_plane(repository)
    plane.cache_seconds = 0
    service = DynamicWorkflowService(
        object(), slack_definitions(), _SlackConnections(), object(),
        control_plane=plane,
    )
    assert service._slack_family_state(TENANT).get("slack_messaging") is not True

    repository.set_capability_family_enabled(TENANT, "slack_messaging", True, 100)

    assert service._slack_family_state(TENANT)["slack_messaging"] is True


def test_a_stopped_account_refuses_the_inbound_turn_before_interpreting_it(
    tmp_path,
):
    repository = _repository(tmp_path)
    repository.set_capability_family_enabled(TENANT, "slack_messaging", True, 100)
    repository.set_emergency_stop(
        TENANT, True, 200, reason="paged", acting_principal_id="user:ana",
    )

    class _NeverCalledBrain:
        def understand_slack(self, text, context):
            raise AssertionError("a stopped account must not reach the model")

    service = DynamicWorkflowService(
        _NeverCalledBrain(), slack_definitions(), _SlackConnections(), object(),
        control_plane=_control_plane(repository),
    )

    result = service.coordinate_slack_turn(TENANT, "user:ana", "manda un mensaje")

    assert result["error"]["code"] == "emergency_stop"
    assert result["recovery"]["action"] == "contact_admin"


def test_lifting_the_stop_restores_the_families_that_were_already_on(tmp_path):
    repository = _repository(tmp_path)
    repository.set_capability_family_enabled(TENANT, "slack_messaging", True, 100)
    repository.set_emergency_stop(
        TENANT, True, 200, reason="paged", acting_principal_id="user:ana",
    )
    plane = _control_plane(repository)
    plane.cache_seconds = 0
    assert plane.family_flags(TENANT) == {"slack_messaging": False}

    repository.set_emergency_stop(
        TENANT, False, 300, acting_principal_id="user:ana",
    )

    # A stop parks work; it does not silently rewrite what the account holds.
    assert plane.family_flags(TENANT) == {"slack_messaging": True}
    assert plane.decide(
        TENANT, capability_id="slack.message.send", effect="write",
    )


def test_the_stop_record_survives_being_lifted(tmp_path):
    repository = _repository(tmp_path)
    repository.set_emergency_stop(
        TENANT, True, 200, reason="paged", acting_principal_id="user:ana",
    )

    state = repository.set_emergency_stop(
        TENANT, False, 300, acting_principal_id="user:ben",
    )

    # "This account was stopped at 200, by whom, and why" is exactly what an
    # operator asks afterwards, and a deleted row cannot answer it.
    assert state["emergency_stop"] is False
    assert state["stopped_at"] == 200
    assert state["stopped_by_principal_id"] == "user:ana"


def test_a_stop_denies_writes_and_names_the_stop_not_a_family(tmp_path):
    repository = _repository(tmp_path)
    repository.set_capability_family_enabled(TENANT, "slack_messaging", True, 100)
    repository.set_emergency_stop(
        TENANT, True, 200, acting_principal_id="user:ana",
    )
    plane = _control_plane(repository)

    decision = plane.decide(
        TENANT, capability_id="slack.message.send", effect="write",
    )

    assert decision.reason == EMERGENCY_STOP
