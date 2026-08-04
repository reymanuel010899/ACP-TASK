"""U7 contract: one versioned projection the client can trust.

Written before the projection changes, per the unit's execution note. Each
test states a promise the client depends on; none of them are about how the
projection is built.
"""

import pytest

from web.concierge import _conversation_response


def _conversation(**overrides):
    base = {
        "conversation_id": "conversation:1",
        "status": "awaiting_approval",
        "state_version": 7,
        "locale": "es",
        "pending_draft": {
            "draft_hash": "hash-1", "destination_label": "#general",
            "text": "Hola", "workflow_run_id": "workflow:1",
            "workflow_revision_id": "revision:1",
        },
    }
    base.update(overrides)
    return base


def test_a_snapshot_carries_the_version_it_speaks_for():
    projection = _conversation_response(_conversation())

    # Without a version the client cannot tell a stale poll from a fresh one,
    # so it cannot refuse to regress.
    assert projection["stateVersion"] == 7


def test_a_snapshot_says_which_actions_are_valid_right_now():
    awaiting = _conversation_response(_conversation())
    executing = _conversation_response(_conversation(
        status="executing", pending_draft=None,
    ))
    finished = _conversation_response(_conversation(
        status="succeeded", pending_draft=None,
    ))

    # The client must never offer an action the server would refuse, and must
    # never invent one the server did not allow.
    assert set(awaiting["allowedActions"]) == {"approve", "reject", "correct"}
    assert executing["allowedActions"] == []
    assert finished["allowedActions"] == []


def test_a_snapshot_says_whether_the_conversation_is_over():
    for status in ("succeeded", "ready", "failed", "expired", "closed"):
        assert _conversation_response(
            _conversation(status=status, pending_draft=None)
        )["terminal"] is True
    for status in ("awaiting_approval", "retrieving", "needs_input"):
        assert _conversation_response(
            _conversation(status=status)
        )["terminal"] is False


def test_effects_are_projected_one_row_each_with_their_own_actions():
    projection = _conversation_response(_conversation(
        pending_draft=None,
        effect_group={
            "group_id": "group:1",
            "effects": [
                {
                    "effect_id": "effect:1", "capability_id": "slack.reaction.add",
                    "summary": "React to the last message", "status": "approved",
                    "reinforced": False,
                },
                {
                    "effect_id": "effect:2", "capability_id": "slack.channel.archive",
                    "summary": "Archive #ideas", "status": "awaiting_approval",
                    "reinforced": True,
                },
            ],
        },
    ))

    effects = projection["effectGroup"]["effects"]
    assert [item["effectId"] for item in effects] == ["effect:1", "effect:2"]
    # Approving one must never be able to authorise the other.
    assert effects[0]["allowedActions"] == []
    assert set(effects[1]["allowedActions"]) == {"approve", "reject"}
    # Reinforced effects open their details, so high risk is not one click away
    # from being invisible.
    assert effects[0]["detailsExpanded"] is False
    assert effects[1]["detailsExpanded"] is True


def test_a_partial_outcome_reports_both_effects_without_a_verdict():
    projection = _conversation_response(_conversation(
        status="ready", pending_draft=None,
        effect_group={
            "group_id": "group:1",
            "effects": [
                {"effect_id": "effect:1", "capability_id": "slack.message.send",
                 "summary": "Post to #general", "status": "succeeded"},
                {"effect_id": "effect:2", "capability_id": "slack.reaction.add",
                 "summary": "React", "status": "failed",
                 "recovery": "retry_safe"},
            ],
        },
    ))

    group = projection["effectGroup"]
    assert [item["status"] for item in group["effects"]] == ["succeeded", "failed"]
    assert group["summary"] == "1 of 2 completed"
    # There is no aggregate verdict, because the group was never atomic.
    assert "outcome" not in group
    assert group["effects"][1]["recovery"] == "retry_safe"


def test_projection_lag_is_stated_rather_than_hidden():
    behind = _conversation_response(_conversation(
        projected_version=5,
    ))
    current = _conversation_response(_conversation(projected_version=7))

    # A client that cannot tell it is looking at a lagging read-model will
    # present stale state as settled.
    assert behind["projectionLag"] is True
    assert current["projectionLag"] is False
