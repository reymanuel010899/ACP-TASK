"""Contacts as trusted capabilities: the manifest, the join, and the guard.

The unit's claim is that an agent can find and propose but never invent, leak,
or silently mutate. Three separate mechanisms carry that claim, and each is
tested here against the specific way it fails silently:

* **The manifest/catalog split.** A manifest that could declare a scope or an
  effect would be a second place authority lives, and the second place always
  wins by accident. The join refuses it.
* **The first-party runtime.** Contacts has no connection, no credential and
  no scopes, and the registry demands all three. The synthetic snapshot is the
  answer, and it has to fail closed for an unbound tenant -- otherwise the
  fix would be worse than the problem it solved.
* **The authority-free scalar guard.** A hallucinated Slack channel id fails
  at Slack. A hallucinated telephone number reaches a person and is billed.

Plus the parity assertion, which is here because the repository already
carries three trusted Slack capabilities that no interface can reach. A review
checklist did not catch that; an executable assertion does.
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from agents.orchestrator.dynamic_workflow_service import DynamicWorkflowService
from agents.orchestrator.slack_operations import (
    CONTACTS_MANIFEST,
    CONTACTS_MANIFEST_VERSION,
    OperationManifestSpec,
    SlackOperationManifestError,
    load_contacts_operations,
    load_operations,
)
from agents.orchestrator.workflow_models import (
    SlackInterpretation,
    SlackInterpretationSlot,
    SlackOperationCandidate,
)
from libs.integrations.catalog import (
    CONTACTS_PROVIDER,
    FIRST_PARTY_CREDENTIAL_VERSION,
    FIRST_PARTY_STORE_CREDENTIAL,
    BRANCH_DIMENSION,
    CapabilityUnavailable,
    ProviderRuntimeRegistry,
    build_contacts_runtime,
    contacts_definitions,
    contacts_scopes,
    first_party_connection_snapshot,
    provider_definitions,
    provider_registration,
    registered_providers,
    slack_definitions,
    synthetic_scope,
)


MANIFEST = Path(__file__).parents[2] / "config" / "contacts_operations_v1.yaml"
ROLLOUT = "production-v1"
TENANT = "org:acme"
BRANCH = "branch:01JBQ9YHY3W4M9K1Q7S2X8T5ZQ"

#: Presentation kinds a surface can actually render. The parity assertion
#: compares against this rather than against "some non-empty string", because
#: a manifest entry naming a kind nothing renders is the same gap as no entry.
RENDERABLE_PRESENTATIONS = frozenset({
    "contact_candidates", "contact_tree", "consent_axes", "contact_activity",
    "audience_preview", "proposal_receipt", "grouping_receipt",
})

#: Trusted Slack capabilities no manifest operation can reach. Named here so
#: the gap is a reviewed exception with a shape rather than an accident, and
#: so adding a second one fails this test.
#:
#: The plan names three -- ``slack.reaction.remove``, ``slack.message.pin``
#: and ``slack.message.unpin``. All three have since been given manifest
#: operations, which is exactly the outcome an executable assertion is for:
#: the prose went stale and the assertion did not.
KNOWN_UNREACHABLE_SLACK_CAPABILITIES = frozenset({"slack.file.upload"})


def _keys(value):
    if isinstance(value, dict):
        return set(value).union(*(_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_keys(item) for item in value), set())
    return set()


def _manifest(tmp_path, mutate):
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    mutate(payload)
    target = tmp_path / "contacts-operations.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def _registry():
    return load_contacts_operations(contacts_definitions())


def _all_families(registry=None):
    return {family: True for family in (registry or _registry()).family_flags}


class _NoConnections:
    """A connection repository the contacts path must never need."""

    def __init__(self):
        self.calls = []

    def list_tenant_installations(self, tenant, provider):
        self.calls.append((tenant, provider))
        return []


class _ProposingBrain:
    def __init__(self, interpretation):
        self.interpretation = interpretation
        self.contexts = []

    def understand_slack(self, text, context):
        self.contexts.append(context)
        return self.interpretation


def _service(brain=None, connections=None, families=None, **kwargs):
    return DynamicWorkflowService(
        brain or _ProposingBrain(None),
        provider_definitions(),
        connections or _NoConnections(),
        object(),
        rollout_version=ROLLOUT,
        contacts_family_flags=_all_families() if families is None else families,
        **kwargs,
    )


# -- the manifest ----------------------------------------------------------

def test_the_manifest_is_json_despite_its_extension_and_declares_no_authority():
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert payload["manifest_version"] == CONTACTS_MANIFEST_VERSION
    assert payload["provider"] == CONTACTS_PROVIDER
    operation_keys = _keys(payload["operations"])
    for trusted_only_field in (
        "input_schema", "output_schema", "required_scopes", "effect", "risk",
        "retry_policy", "verifier", "rollout_version",
    ):
        assert trusted_only_field not in operation_keys


def test_the_manifest_ports_method_coverage_so_exclusions_are_reviewable():
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    coverage = payload["method_coverage"]

    assert set(coverage) == {"supported", "conditional", "excluded"}
    assert all(
        entry["prerequisites"]
        for status in coverage.values() for entry in status
    )
    assert all(entry["reason"] for entry in coverage["excluded"])
    excluded = {entry["method"] for entry in coverage["excluded"]}
    # The four mutations a human owns. If any of them ever acquires an
    # agent-side capability, it has to leave this list first.
    assert {
        "ContactsRepository.create_contact",
        "ContactsRepository.add_address",
        "ContactsConsentRepository.grant_consent",
        "ContactsConsentRepository.activate_address",
    } <= excluded


def test_a_manifest_that_tries_to_declare_a_scope_is_refused(tmp_path):
    def add_scope(payload):
        payload["operations"][0]["required_scopes"] = ["contacts:directory:read"]

    with pytest.raises(SlackOperationManifestError):
        load_contacts_operations(
            contacts_definitions(), _manifest(tmp_path, add_scope),
        )


def test_a_contacts_operation_may_not_borrow_slacks_catalog(tmp_path):
    def swap(payload):
        payload["operations"][0]["capability_recipe"][0]["capability_id"] = \
            "slack.channels.list"

    with pytest.raises(SlackOperationManifestError):
        load_contacts_operations(
            contacts_definitions() + slack_definitions(),
            _manifest(tmp_path, swap),
        )


def test_a_local_contacts_operation_may_not_carry_a_capability_recipe(tmp_path):
    def localize(payload):
        payload["operations"][0]["operation_kind"] = "local"
        payload["operations"][0]["authority_profile"] = "none"

    with pytest.raises(SlackOperationManifestError):
        load_contacts_operations(
            contacts_definitions(), _manifest(tmp_path, localize),
        )


def test_the_contacts_manifest_cannot_be_loaded_as_another_providers(tmp_path):
    spec = replace(
        CONTACTS_MANIFEST, provider="slack",
        manifest_version="slack.operations.v1",
    )

    with pytest.raises(SlackOperationManifestError):
        load_operations(spec, contacts_definitions())


def test_an_operation_manifest_spec_must_namespace_its_version():
    with pytest.raises(SlackOperationManifestError):
        OperationManifestSpec(
            provider="contacts", manifest_version="slack.operations.v1",
            manifest_path=MANIFEST,
        )


# -- parity ----------------------------------------------------------------

def test_every_contacts_capability_is_reachable_and_every_operation_renders():
    """The gap this test exists to stop recurring, made executable.

    Two directions, because each hides a different failure. A capability with
    no operation is authority nobody can invoke and nobody notices. An
    operation whose presentation nothing renders is an entry that passes
    review and produces a blank card.
    """
    registry = _registry()
    service = _service()
    projection = service.contacts_operation_projection(TENANT)

    reachable = {
        step.capability_id
        for operation in registry.operations
        for step in operation.capability_recipe
    }
    assert reachable == {
        definition.capability_id for definition in contacts_definitions()
    }
    assert {item["operation_id"] for item in projection} == {
        operation.operation_id for operation in registry.operations
    }
    for item in projection:
        assert item["presentation"]["kind"] in RENDERABLE_PRESENTATIONS
        assert item["presentation"]["label"]


def test_the_unreachable_slack_capabilities_stay_a_named_exception():
    from agents.orchestrator.slack_operations import load_slack_operations

    registry = load_slack_operations(slack_definitions())
    reachable = {
        step.capability_id
        for operation in registry.operations
        for step in operation.capability_recipe
    }
    unreachable = {
        definition.capability_id for definition in slack_definitions()
    } - reachable

    # Not asserted empty, because it is not empty and pretending otherwise
    # would delete the signal. Asserted *exactly*, so a fourth one fails here.
    assert unreachable == KNOWN_UNREACHABLE_SLACK_CAPABILITIES


def test_the_projection_carries_language_only_and_never_a_capability_id():
    projection = _service().contacts_operation_projection(TENANT)

    assert projection
    for item in projection:
        assert set(item) == {
            "operation_id", "operation_kind", "availability", "aliases",
            "slots", "prerequisites", "recovery", "presentation",
        }
        assert "capability_recipe" not in item


# -- the first-party runtime ----------------------------------------------

def test_contacts_is_registered_once_and_carries_no_refreshable_credential():
    assert set(registered_providers()) == {"google", "slack", "contacts", "twilio"}
    registration = provider_registration(CONTACTS_PROVIDER)
    assert registration.manifest_version == CONTACTS_MANIFEST_VERSION
    assert registration.credential_strategy is FIRST_PARTY_STORE_CREDENTIAL


def test_a_first_party_store_refuses_to_mint_provider_authority():
    # Not an empty token, and not a no-op. If a contacts capability ever
    # reaches the outbound dispatch path, the right outcome is a loud failure.
    with pytest.raises(PermissionError):
        FIRST_PARTY_STORE_CREDENTIAL.authority(b"{}", None)


def test_a_synthetic_snapshot_resolves_a_contacts_capability_like_any_other():
    registry = ProviderRuntimeRegistry([build_contacts_runtime(object())])
    snapshot = first_party_connection_snapshot(
        TENANT, "contacts.search", "1.0.0", ROLLOUT, branch_ids=(BRANCH,),
    )

    binding = registry.resolve(snapshot, ROLLOUT)

    assert binding.definition.capability_id == "contacts.search"
    assert snapshot.credential_version == FIRST_PARTY_CREDENTIAL_VERSION
    assert snapshot.connection_id == "first-party:contacts:%s" % TENANT
    assert synthetic_scope(CONTACTS_PROVIDER, BRANCH_DIMENSION, BRANCH) in \
        snapshot.effective_scopes


def test_an_unbound_tenant_mints_nothing_at_all():
    """KTD11's local-tenant fallback, made a hard failure.

    The whole authority of a first-party store is "a tenant was resolved". If
    that can be skipped, the synthetic snapshot is a way around row-level
    security rather than a way to satisfy the registry.
    """
    for unbound in (None, "", "   "):
        with pytest.raises(CapabilityUnavailable):
            first_party_connection_snapshot(
                unbound, "contacts.search", "1.0.0", ROLLOUT,
            )
    assert contacts_scopes("", (BRANCH,)) == frozenset()


def test_a_snapshot_missing_a_family_scope_cannot_resolve_that_family():
    registry = ProviderRuntimeRegistry([build_contacts_runtime(object())])
    read_only = first_party_connection_snapshot(
        TENANT, "contacts.propose", "1.0.0", ROLLOUT,
        families=("directory:read",),
    )

    with pytest.raises(CapabilityUnavailable):
        registry.resolve(read_only, ROLLOUT)


def test_a_stale_rollout_or_an_unhealthy_first_party_connection_fails_closed():
    registry = ProviderRuntimeRegistry([build_contacts_runtime(object())])
    snapshot = first_party_connection_snapshot(
        TENANT, "contacts.search", "1.0.0", ROLLOUT,
    )

    with pytest.raises(CapabilityUnavailable):
        registry.resolve(snapshot, "production-v2")
    with pytest.raises(CapabilityUnavailable):
        registry.resolve(replace(snapshot, health="degraded"), ROLLOUT)


def test_two_tenants_never_share_a_first_party_connection_or_its_branches():
    acme = first_party_connection_snapshot(
        TENANT, "contacts.search", "1.0.0", ROLLOUT, branch_ids=(BRANCH,),
    )
    globex = first_party_connection_snapshot(
        "org:globex", "contacts.search", "1.0.0", ROLLOUT,
    )

    assert acme.connection_id != globex.connection_id
    assert acme.tenant_id != globex.tenant_id
    assert synthetic_scope(CONTACTS_PROVIDER, BRANCH_DIMENSION, BRANCH) \
        not in globex.effective_scopes


# -- the catalog -----------------------------------------------------------

def test_the_write_surface_is_two_proposals_and_two_reversible_groupings():
    writes = {
        definition.capability_id: definition
        for definition in contacts_definitions()
        if definition.effect == "write"
    }

    assert set(writes) == {
        "contacts.propose", "contacts.update.propose",
        "contacts.list.add", "contacts.tag.apply",
    }
    # There is no paired "with approval" / "without approval" variant of any
    # mutation, which is what would give the agent a path around the human.
    assert not any("approval" in name for name in writes)
    for capability_id in ("contacts.propose", "contacts.update.propose"):
        assert writes[capability_id].verifier == "contacts.proposal"
        assert writes[capability_id].preview_fields
    for capability_id in ("contacts.list.add", "contacts.tag.apply"):
        # Reversible, no consent semantics, reaches nobody: idempotent retry
        # is safe and no proposal is warranted.
        assert writes[capability_id].retry_policy == "idempotent"
        assert writes[capability_id].risk == "low"


def test_every_contacts_capability_acts_as_the_account_and_nobody_else():
    for definition in contacts_definitions():
        assert definition.provider == CONTACTS_PROVIDER
        # There is no consenting person and no installation to act as.
        assert definition.authority_profile == "account"
        assert definition.required_scopes
        assert all(
            scope.startswith("contacts:")
            for scope in definition.required_scopes
        )


def test_no_contacts_input_schema_accepts_a_free_text_destination():
    """The second half of the guard, in the schema rather than the model.

    The workflow-models guard stops a model emitting a destination. This stops
    anything that is not a resolver output reaching an input named for one,
    including a hand-built payload that never passed through the model.
    """
    for definition in contacts_definitions():
        for name, schema in definition.input_schema["properties"].items():
            if name.endswith("_id") or name.endswith("_ref"):
                assert schema.get("pattern"), (definition.capability_id, name)
        assert "address" not in definition.input_schema["properties"]
        assert "phone" not in definition.input_schema["properties"]


# -- the guard -------------------------------------------------------------

@pytest.mark.parametrize("value", [
    "+34600111222",
    "+34 600 111 222",
    "600111222",
    "whatsapp:+34600111222",
    "sms:+34600111222",
    "tel:+34600111222",
    "ana.perez@example.com",
    "contact:01JBQ9YHY3W4M9K1Q7S2X8T5ZQ",
    "list:01JBQ9YHY3W4M9K1Q7S2X8T5ZQ",
    "segment:01JBQ9YHY3W4M9K1Q7S2X8T5ZQ",
    "campaign:01JBQ9YHY3W4M9K1Q7S2X8T5ZQ",
])
def test_a_model_may_not_emit_a_destination_or_a_resolved_identifier(value):
    with pytest.raises(ValidationError):
        SlackInterpretationSlot(
            name="query", value=value, provenance="current_turn",
        )


@pytest.mark.parametrize("value", [
    "Ana Pérez",
    "llámame al +34600111222",
    "2026-08-04",
    "general",
    "100",
])
def test_ordinary_language_still_passes_the_guard(value):
    slot = SlackInterpretationSlot(
        name="query", value=value, provenance="current_turn",
    )

    assert slot.value == value


def test_a_slot_named_for_a_destination_is_refused_before_its_value_matters():
    for name in (
        "phone", "destination", "recipient", "contact_id", "list_id",
        "segment_id", "campaign_id", "address",
    ):
        with pytest.raises(ValidationError):
            SlackInterpretationSlot(
                name=name, value="Ana", provenance="current_turn",
            )


def test_a_correction_cannot_smuggle_a_destination_past_the_slot_guard():
    from agents.orchestrator.workflow_models import (
        SlackInterpretationCorrection,
    )

    with pytest.raises(ValidationError):
        SlackInterpretationCorrection(
            slot="query", replacement="+34600111222",
            provenance="current_turn",
        )


def test_an_operation_id_outside_a_trusted_namespace_is_refused():
    with pytest.raises(ValidationError):
        SlackOperationCandidate(operation_id="twilio.sms.send", confidence=0.9)
    assert SlackOperationCandidate(
        operation_id="contacts.resolve", confidence=0.9,
    ).operation_id == "contacts.resolve"


# -- the service -----------------------------------------------------------

def test_a_capability_absent_from_the_catalog_stops_at_plan_compile():
    """AE9. Named limitation, no provider call, nothing planned."""
    brain = _ProposingBrain(SlackInterpretation(
        operations=[SlackOperationCandidate(
            operation_id="contacts.merge", confidence=0.95,
        )],
        locale="es", confidence=0.95,
    ))
    connections = _NoConnections()
    service = _service(brain, connections)

    result = service.coordinate_slack_turn(
        TENANT, "user:1", "fusiona los contactos duplicados",
    )

    assert result["error"]["code"] == "unsupported_operation"
    assert result["error"]["operation_id"] == "contacts.merge"
    assert result["recovery"]["action"] == "choose_supported_operation"


def test_a_contacts_operation_the_tenant_holds_reaches_the_model_projection():
    brain = _ProposingBrain(SlackInterpretation(
        operations=[SlackOperationCandidate(
            operation_id="contacts.resolve", confidence=0.95,
        )],
        slots=[SlackInterpretationSlot(
            name="query", value="Ana Pérez", provenance="current_turn",
        )],
        locale="es", confidence=0.95,
    ))
    service = _service(brain)

    service.coordinate_slack_turn(TENANT, "user:1", "¿quién es Ana Pérez?")

    visible = {
        item["operation_id"]
        for item in brain.contexts[0]["slack_operation_projection"]
    }
    assert "contacts.resolve" in visible
    assert "contacts.propose" in visible


def test_a_family_nobody_enabled_hides_its_operations_and_names_itself():
    brain = _ProposingBrain(SlackInterpretation(
        operations=[SlackOperationCandidate(
            operation_id="contacts.propose", confidence=0.9,
        )],
        locale="es", confidence=0.9,
    ))
    families = _all_families()
    families["contacts_proposals"] = False
    service = _service(brain, families=families)

    result = service.coordinate_slack_turn(
        TENANT, "user:1", "propón un contacto nuevo",
    )

    assert result["error"]["code"] == "feature_disabled"
    assert result["error"]["feature"] == "contacts_proposals"
    assert "contacts.propose" not in {
        item["operation_id"]
        for item in service.contacts_operation_projection(TENANT)
    }


def test_contacts_families_are_off_until_somebody_turns_them_on():
    service = DynamicWorkflowService(
        _ProposingBrain(None), provider_definitions(), _NoConnections(),
        object(), rollout_version=ROLLOUT,
    )

    # A first-party store has no install callback to derive enablement from,
    # so the default is the only thing standing between registering a catalog
    # entry and exposing personal data to every tenant on the process.
    assert service.contacts_operation_projection(TENANT) == ()
    assert set(service._contacts_family_state(TENANT).values()) == {False}


def test_the_contacts_path_never_asks_for_a_slack_installation():
    brain = _ProposingBrain(SlackInterpretation(
        operations=[SlackOperationCandidate(
            operation_id="contacts.search", confidence=0.9,
        )],
        locale="es", confidence=0.9,
    ))
    connections = _NoConnections()
    service = _service(brain, connections)

    result = service.coordinate_slack_turn(TENANT, "user:1", "buscar contacto")

    # An unavailable contacts operation must never tell somebody to connect
    # Slack, and a reachable one must not be blocked by a missing install.
    assert result.get("error", {}).get("code") != "connection_unavailable"
    assert connections.calls == [(TENANT, "slack")]


def test_an_unknown_namespace_lands_on_a_limitation_rather_than_a_registry():
    service = _service()

    assert service._registry_for("twilio.sms.send") is None
    assert service._registry_for("contacts.resolve") is \
        service.contacts_operation_registry
    assert service._registry_for("slack.message.send") is \
        service.slack_operation_registry
