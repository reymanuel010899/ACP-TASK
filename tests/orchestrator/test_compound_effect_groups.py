"""U7 slice B: a compound request becomes a group of separately answerable
effects. Written before the implementation, per the unit's execution note.

A group is not a transaction. These tests exist mostly to pin down what must
*not* happen: one approval must not carry another, and a mixed outcome must not
be reported as a verdict.
"""

import pytest

from agents.orchestrator.compound import (
    build_effect_group,
    apply_effect_decision,
    group_outcome,
)


def _operations():
    return [
        {"operation_id": "slack.reaction.add", "confidence": 0.9},
        {"operation_id": "slack.direct_message.send", "confidence": 0.9},
    ]


def test_a_compound_request_becomes_one_row_per_effect():
    group = build_effect_group("conversation:1", _operations(), {})

    assert [item["capability_id"] for item in group["effects"]] == [
        "slack.reaction.add", "slack.direct_message.send",
    ]
    # Every effect is separately identifiable, or nothing downstream can
    # approve, reject, or report on one without touching the others.
    assert len({item["effect_id"] for item in group["effects"]}) == 2
    assert all(item["status"] == "awaiting_approval"
               for item in group["effects"])


def test_reads_resolve_before_effects_are_offered():
    # The interpretation declares that the write derives from the read.
    group = build_effect_group("conversation:1", [
        {"operation_id": "slack.conversation.read", "confidence": 0.9},
        {"operation_id": "slack.message.send", "confidence": 0.9},
    ], {}, dependencies=[{"operation_index": 1, "depends_on_index": 0}])

    read, write = group["effects"]
    assert read["effect_kind"] == "read"
    assert write["effect_kind"] == "write"
    # The write is derived from the read, so it cannot be previewed exactly
    # until the read has produced what it will say.
    assert write["depends_on"] == [read["effect_id"]]
    assert write["status"] == "blocked"


def test_approving_one_effect_never_authorises_another():
    group = build_effect_group("conversation:1", _operations(), {})
    first, second = group["effects"]

    updated = apply_effect_decision(group, first["effect_id"], "approve")

    assert updated["effects"][0]["status"] == "approved"
    assert updated["effects"][1]["status"] == "awaiting_approval"


def test_rejecting_one_effect_leaves_the_others_answerable():
    group = build_effect_group("conversation:1", _operations(), {})
    first, second = group["effects"]

    updated = apply_effect_decision(group, second["effect_id"], "reject")

    assert updated["effects"][1]["status"] == "rejected"
    assert updated["effects"][0]["status"] == "awaiting_approval"


def test_a_decision_on_an_unknown_effect_changes_nothing():
    group = build_effect_group("conversation:1", _operations(), {})

    with pytest.raises(KeyError):
        apply_effect_decision(group, "effect:not-here", "approve")


def test_correcting_an_effect_invalidates_the_group_approval_only():
    group = build_effect_group("conversation:1", _operations(), {})
    first, second = group["effects"]
    group = apply_effect_decision(group, first["effect_id"], "approve")
    group = apply_effect_decision(group, second["effect_id"], "approve")

    corrected = apply_effect_decision(group, second["effect_id"], "correct")

    # Correcting the second effect must not silently keep an approval that was
    # given for different content.
    assert corrected["effects"][1]["status"] == "awaiting_approval"
    # The unchanged first effect keeps the approval it was actually given.
    assert corrected["effects"][0]["status"] == "approved"


def test_a_mixed_outcome_is_reported_without_a_verdict():
    group = build_effect_group("conversation:1", _operations(), {})
    first, second = group["effects"]
    group = apply_effect_decision(group, first["effect_id"], "succeeded")
    group = apply_effect_decision(group, second["effect_id"], "failed")

    outcome = group_outcome(group)

    assert outcome["completed"] == 1
    assert outcome["total"] == 2
    assert outcome["summary"] == "1 of 2 completed"
    # No aggregate pass or fail: the group never promised atomicity.
    assert "outcome" not in outcome
    assert outcome["terminal"] is True


def test_a_group_is_not_terminal_while_anything_can_still_happen():
    group = build_effect_group("conversation:1", _operations(), {})
    group = apply_effect_decision(group, group["effects"][0]["effect_id"],
                                  "succeeded")

    assert group_outcome(group)["terminal"] is False


def test_independent_effects_are_not_linked_just_because_one_reads():
    group = build_effect_group("conversation:1", [
        {"operation_id": "slack.conversation.read"},
        {"operation_id": "slack.reaction.add"},
    ], {})

    read, reaction = group["effects"]
    # Reacting to a message does not derive its content from a summary, so
    # linking them would let one failing silently strand the other.
    assert reaction["depends_on"] == []
    assert reaction["status"] == "awaiting_approval"
    assert read["status"] == "awaiting_approval"
