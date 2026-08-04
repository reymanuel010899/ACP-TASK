"""U8 descriptor conformance: what a capability must prove before it ships.

The unit's execution note is the whole point of this file — a family cannot be
enabled merely because its connector method works. Every registered operation
has to carry the evidence that makes it reviewable, authorised, previewable,
and truthful, or it has no business being dispatchable.

These assertions are deliberately about the *set* of registered capabilities,
not a hand-kept list, so a new descriptor is held to the same bar the day it is
added rather than the day someone remembers to extend a test.
"""

import inspect

import jsonschema
import pytest

from libs.connectors.slack import SlackActionExecutor
from libs.integrations.catalog import (
    capability_reinforced,
    capability_retry_policy,
    slack_definitions,
)


DEFINITIONS = slack_definitions()
EXECUTOR_SOURCE = inspect.getsource(SlackActionExecutor)


def _ids(definitions):
    return [item.capability_id for item in definitions]


@pytest.mark.parametrize("definition", DEFINITIONS, ids=_ids(DEFINITIONS))
def test_every_capability_declares_a_usable_input_schema(definition):
    schema = definition.input_schema

    jsonschema.Draft7Validator.check_schema(schema)
    assert schema.get("type") == "object"
    # An open schema cannot state what a preview will contain, so the approval
    # would be for something unbounded.
    assert schema.get("additionalProperties") is False


@pytest.mark.parametrize("definition", DEFINITIONS, ids=_ids(DEFINITIONS))
def test_every_capability_declares_a_filtered_output_schema(definition):
    schema = definition.output_schema

    jsonschema.Draft7Validator.check_schema(schema)
    assert schema.get("type") == "object"
    # Provider payloads carry far more than the product needs. An unfiltered
    # output is how raw provider content reaches storage and prompts.
    assert schema.get("additionalProperties") is False
    assert schema.get("properties")


@pytest.mark.parametrize("definition", DEFINITIONS, ids=_ids(DEFINITIONS))
def test_every_capability_names_the_authority_it_needs(definition):
    assert definition.required_scopes, "a capability with no scope is unbounded"
    assert all(isinstance(scope, str) and scope
               for scope in definition.required_scopes)
    assert definition.authority_profile in ("bot", "user", "enterprise_admin")


@pytest.mark.parametrize("definition", DEFINITIONS, ids=_ids(DEFINITIONS))
def test_every_capability_has_an_executor_route(definition):
    # A descriptor nobody can dispatch is worse than an absent one: it
    # advertises authority the product cannot exercise.
    assert '"%s"' % definition.capability_id in EXECUTOR_SOURCE


@pytest.mark.parametrize(
    "definition", [item for item in DEFINITIONS if item.effect == "write"],
    ids=_ids([item for item in DEFINITIONS if item.effect == "write"]),
)
def test_every_write_is_previewable_verifiable_and_recoverable(definition):
    # Nobody can approve what they cannot see.
    assert definition.preview_fields
    assert all(field in definition.input_schema["properties"]
               for field in definition.preview_fields), (
        "a preview field that is not an input cannot describe the effect"
    )
    # A write nobody can check afterwards cannot be reported truthfully.
    assert definition.verifier
    # Every write says how a repeat behaves, because that decides whether an
    # unknown outcome retries or waits for reconciliation.
    assert definition.retry_policy == capability_retry_policy(
        definition.capability_id, "write",
    )
    assert definition.retry_policy in ("idempotent", "reconcile")


@pytest.mark.parametrize(
    "definition", [item for item in DEFINITIONS if item.effect == "read"],
    ids=_ids([item for item in DEFINITIONS if item.effect == "read"]),
)
def test_a_read_never_pretends_to_need_approval(definition):
    assert definition.preview_fields == ()
    assert definition.verifier is None
    assert definition.retry_policy == "safe"


def test_reinforced_effects_are_exactly_the_ones_that_reshape_shared_space():
    reinforced = {
        item.capability_id for item in DEFINITIONS if item.reinforced
    }

    # Channel administration changes the space everyone in it works in. Nothing
    # else should demand someone be present, or step-up becomes a tax.
    assert reinforced == {
        item.capability_id for item in DEFINITIONS
        if item.capability_id.startswith("slack.channel.")
    }
    assert all(capability_reinforced(item) for item in reinforced)
    assert reinforced, "the reinforced set should not silently empty"


def test_no_capability_can_be_registered_twice_at_one_version():
    keys = [(item.capability_id, item.version) for item in DEFINITIONS]

    assert len(keys) == len(set(keys))


def test_scope_declarations_match_what_the_install_asks_for():
    from libs.connectors.slack import slack_scope_catalog

    catalog = slack_scope_catalog()

    # The install list is derived, not copied. If these ever diverge again, a
    # connection can be authorised that cannot run what it advertises.
    assert catalog == {
        item.capability_id: frozenset(item.required_scopes)
        for item in DEFINITIONS
    }
