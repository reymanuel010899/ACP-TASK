"""U7: dispatching an approved group, one effect at a time.

The group is not a transaction, so dispatch must not behave like one: only
approved effects run, a blocked effect waits for what it depends on, and one
effect failing does not cancel the rest.
"""

import pytest

from agents.orchestrator.compound import (
    apply_effect_decision,
    build_effect_group,
    dispatchable_effects,
)


def _group():
    # Only the send derives from the read; the reaction stands alone.
    return build_effect_group("conversation:1", [
        {"operation_id": "slack.conversation.read"},
        {"operation_id": "slack.message.send"},
        {"operation_id": "slack.reaction.add"},
    ], {}, dependencies=[{"operation_index": 1, "depends_on_index": 0}])


def test_only_approved_effects_are_dispatchable():
    group = _group()
    read, write, reaction = group["effects"]
    group = apply_effect_decision(group, read["effect_id"], "approve")

    ready = dispatchable_effects(group)

    # The reaction was never approved, so it must not run just because a
    # sibling was.
    assert [item["effect_id"] for item in ready] == [read["effect_id"]]


def test_a_derived_write_waits_for_the_read_it_depends_on():
    group = _group()
    read, write, _reaction = group["effects"]
    group = apply_effect_decision(group, read["effect_id"], "approve")

    # The write is blocked, so approving it is not even offered yet.
    assert write["status"] == "blocked"
    assert [item["effect_id"] for item in dispatchable_effects(group)] == [
        read["effect_id"],
    ]

    group = apply_effect_decision(group, read["effect_id"], "succeeded")
    group = apply_effect_decision(
        group, group["effects"][1]["effect_id"], "approve",
    )

    assert [item["effect_id"] for item in dispatchable_effects(group)] == [
        write["effect_id"],
    ]


def test_a_failed_effect_does_not_cancel_its_siblings():
    group = _group()
    read, _write, reaction = group["effects"]
    group = apply_effect_decision(group, reaction["effect_id"], "approve")
    group = apply_effect_decision(group, read["effect_id"], "approve")
    group = apply_effect_decision(group, read["effect_id"], "failed")

    ready = dispatchable_effects(group)

    # The reaction stands on its own and was approved on its own.
    assert [item["effect_id"] for item in ready] == [reaction["effect_id"]]


def test_a_write_whose_read_failed_never_becomes_dispatchable():
    group = _group()
    read, write, _reaction = group["effects"]
    group = apply_effect_decision(group, read["effect_id"], "approve")
    group = apply_effect_decision(group, read["effect_id"], "failed")

    # Its content was never produced, so there is nothing exact to send.
    assert write["effect_id"] not in {
        item["effect_id"] for item in dispatchable_effects(group)
    }
    assert group["effects"][1]["status"] == "blocked"


def test_an_already_running_effect_is_not_offered_twice():
    group = _group()
    reaction = group["effects"][2]
    group = apply_effect_decision(group, reaction["effect_id"], "approve")
    group = apply_effect_decision(group, reaction["effect_id"], "dispatched")

    assert dispatchable_effects(group) == []
