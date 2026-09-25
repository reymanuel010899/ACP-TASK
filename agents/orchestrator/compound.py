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
    "dispatched": "dispatched",
}

_TERMINAL = frozenset({"succeeded", "failed", "rejected", "cancelled"})
_COMPLETED = frozenset({"succeeded"})


def effect_kind(capability_id):
    return "read" if capability_id.endswith(_READ_SUFFIXES) else "write"


def build_effect_group(conversation_id, operations, resolved, dependencies=None):
    """Turn interpreted operations into one row per effect, reads first.

    Dependencies are the ones the interpretation declared, not every write
    waiting on every read. "React to that and tell María" has two independent
    effects; linking them would make one failing silently strand the other.

    Ordering is still not cosmetic: a write that *does* derive from a read
    cannot be previewed exactly until the read has produced what it will say,
    so it is created blocked rather than offered for approval against content
    nobody has seen.
    """
    if not conversation_id:
        raise ValueError("an effect group belongs to a conversation")
    named = [item for item in operations if item.get("operation_id")]
    declared = {}
    for edge in (dependencies or []):
        target = edge.get("operation_index")
        source = edge.get("depends_on_index")
        if target is None or source is None:
            continue
        declared.setdefault(int(target), []).append(int(source))
    order = sorted(
        range(len(named)),
        key=lambda index: (
            0 if effect_kind(named[index]["operation_id"]) == "read" else 1,
            index,
        ),
    )
    effect_ids = {index: "effect:%s" % uuid.uuid4().hex for index in order}
    effects = []
    for index in order:
        operation = named[index]
        capability_id = operation["operation_id"]
        kind = effect_kind(capability_id)
        effect_id = effect_ids[index]
        depends_on = [
            effect_ids[source] for source in declared.get(index, ())
            if source in effect_ids
        ]
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


def dispatchable_effects(group):
    """Effects that may run right now: approved, and nothing owed to them.

    Nothing here treats the group as a unit. An effect runs because it was
    approved on its own and its own dependencies produced what it needs; a
    sibling failing neither blocks it nor drags it along.
    """
    succeeded = {
        item["effect_id"] for item in group["effects"]
        if item["status"] in _COMPLETED
    }
    return [
        item for item in group["effects"]
        if item["status"] == "approved"
        and all(needed in succeeded for needed in item["depends_on"])
    ]


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
