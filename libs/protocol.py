"""Canonical Tessera collaboration validation for native services."""

from treessera.protocol import (
    COLLABORATION_STATUSES as SDK_COLLABORATION_STATUSES,
    TASK_ACCEPT,
    TASK_CONTINUE,
    TASK_COUNTER,
    TASK_NEEDS_APPROVAL,
    TASK_NEEDS_INPUT,
    TASK_NEEDS_PERMISSION,
    TASK_OFFER,
    TASK_PROGRESS,
    TASK_REQUEST,
    TASK_RESULT,
)

COLLABORATION_STATUSES = frozenset(SDK_COLLABORATION_STATUSES)


class ProtocolValidationError(ValueError):
    """A protocol envelope is malformed or unsupported."""


def collaboration_envelope(
    status,
    task_id,
    conversation_id,
    reason,
    missing_fields=None,
    options=None,
    recommended_default=None,
    blocking=True,
    input_schema=None,
    permission=None,
    proposal=None,
    progress=None,
):
    envelope = {
        "type": status,
        "task_id": task_id,
        "conversation_id": conversation_id,
        "reason": reason,
        "blocking": blocking,
    }
    optional = {
        "missing_fields": missing_fields,
        "options": options,
        "recommended_default": recommended_default,
        "input_schema": input_schema,
        "permission": permission,
        "proposal": proposal,
        "progress": progress,
    }
    envelope.update({key: value for key, value in optional.items() if value is not None})
    return validate_collaboration_envelope(envelope)


def validate_collaboration_envelope(envelope):
    if not isinstance(envelope, dict) or envelope.get("type") not in COLLABORATION_STATUSES:
        raise ProtocolValidationError("unknown collaboration status")
    for field in ("task_id", "conversation_id", "reason"):
        if not isinstance(envelope.get(field), str) or not envelope[field]:
            raise ProtocolValidationError("%s is required" % field)
    if not isinstance(envelope.get("blocking", True), bool):
        raise ProtocolValidationError("blocking must be boolean")
    status = envelope["type"]
    if status == TASK_NEEDS_INPUT:
        fields = envelope.get("missing_fields")
        if not isinstance(fields, list) or not fields:
            raise ProtocolValidationError("missing_fields is required")
        if not isinstance(envelope.get("input_schema"), dict):
            raise ProtocolValidationError("input_schema is required")
    elif status == TASK_NEEDS_PERMISSION:
        if not isinstance(envelope.get("permission"), str) or not envelope["permission"]:
            raise ProtocolValidationError("permission is required")
    elif status == TASK_NEEDS_APPROVAL:
        if not isinstance(envelope.get("proposal"), dict):
            raise ProtocolValidationError("proposal is required")
    elif status == TASK_PROGRESS:
        value = envelope.get("progress")
        if not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise ProtocolValidationError("progress must be between 0 and 1")
    return envelope
