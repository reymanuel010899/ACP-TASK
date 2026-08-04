"""Compound Slack requests as groups of separately answerable effects.

A compound request — "react to that and tell María" — is not one action with
two parts. It is two effects that happen to have been asked for together, and
treating them as a unit is what produces the two failures this module exists to
prevent: an approval for one silently authorising the other, and a mixed
outcome reported as though the group had passed or failed as a whole.

Nothing here promises atomicity, because Slack offers none. Two effects can
succeed and fail independently, and the honest report says exactly that.
"""

import uuid

#: Reads produce the values a later write says. They run first, and anything
#: derived from them stays blocked until they have.
_READ_SUFFIXES = (".read", ".list", ".search", ".messages", ".permalink")

#: What a decision does to one effect. Correcting returns it to unapproved,
#: because an approval was given for content that no longer stands.
_DECISIONS = {
    "approve": "approved",
    "reject": "rejected",
    "correct": "awaiting_approval",
    "cancel": "cancelled",
    "succeeded": "succeeded",
    "failed": "failed",
}

_TERMINAL = frozenset({"succeeded", "failed", "rejected", "cancelled"})
_COMPLETED = frozenset({"succeeded"})


def effect_kind(capability_id):
    return "read" if capability_id.endswith(_READ_SUFFIXES) else "write"


def build_effect_group(conversation_id, operations, resolved):
    """Turn interpreted operations into one row per effect, reads first.

    Ordering is not cosmetic: a write derived from a read cannot be previewed
    exactly until the read has produced what it will say, so it is created
    blocked rather than offered for approval against content nobody has seen.
    """
    if not conversation_id:
        raise ValueError("an effect group belongs to a conversation")
    ordered = sorted(
        (item for item in operations if item.get("operation_id")),
        key=lambda item: 0 if effect_kind(item["operation_id"]) == "read" else 1,
    )
    effects, read_ids = [], []
    for operation in ordered:
        capability_id = operation["operation_id"]
        kind = effect_kind(capability_id)
        effect_id = "effect:%s" % uuid.uuid4().hex
        depends_on = list(read_ids) if kind == "write" else []
        effects.append({
            "effect_id": effect_id,
            "capability_id": capability_id,
            "effect_kind": kind,
            "summary": _summary(capability_id, resolved),
            "depends_on": depends_on,
            # A write waiting on a read is not yet answerable: approving it
            # would approve content that does not exist yet.
            "status": "blocked" if depends_on else "awaiting_approval",
        })
        if kind == "read":
            read_ids.append(effect_id)
    return {
        "group_id": "group:%s" % uuid.uuid4().hex,
        "conversation_id": conversation_id,
        "effects": effects,
    }


def apply_effect_decision(group, effect_id, decision):
    """Change exactly one effect, and unblock only what that actually frees."""
    status = _DECISIONS.get(decision)
    if status is None:
        raise ValueError("unsupported effect decision")
    effects = [dict(item) for item in group["effects"]]
    target = next(
        (item for item in effects if item["effect_id"] == effect_id), None
    )
    if target is None:
        raise KeyError("effect is not part of this group")
    target["status"] = status
    if status in _COMPLETED:
        _unblock_dependents(effects, effect_id)
    return dict(group, effects=effects)


def _unblock_dependents(effects, finished_id):
    finished = {
        item["effect_id"] for item in effects
        if item["status"] in _COMPLETED
    }
    finished.add(finished_id)
    for effect in effects:
        if effect["status"] != "blocked":
            continue
        if all(item in finished for item in effect["depends_on"]):
            effect["status"] = "awaiting_approval"


def group_outcome(group):
    """Report what happened per effect, and never invent a group verdict."""
    effects = group["effects"]
    completed = sum(1 for item in effects if item["status"] in _COMPLETED)
    return {
        "completed": completed,
        "total": len(effects),
        "summary": "%d of %d completed" % (completed, len(effects)),
        "terminal": all(item["status"] in _TERMINAL for item in effects),
    }


def _summary(capability_id, resolved):
    """A human-readable line naming the exact target, never an id alone."""
    channel = (resolved or {}).get("active_channel") or {}
    person = (resolved or {}).get("active_person") or {}
    target = (
        "#%s" % channel["name"] if channel.get("name")
        else person.get("display_name") or person.get("real_name")
        or channel.get("id") or person.get("id")
    )
    action = capability_id.rsplit(".", 1)[-1].replace("_", " ")
    return "%s %s" % (action, target) if target else action
