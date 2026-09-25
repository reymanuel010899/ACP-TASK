"""Typed planner and interpretation output with no provider authority."""

import re
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_SLACK_PROVIDER_ID = re.compile(
    r"^(?:[BCDEGUTW][A-Z0-9]{8,}|\d{10,}\.\d+)$"
)
_AUTHORITY_FIELD_MARKERS = (
    "approval", "capability", "connection", "credential", "provider_id",
    "scope", "token", "team_id", "channel_id", "user_id", "message_ts",
    # Destination-shaped field names. A slot the model *names* for a
    # destination is refused before its value is even looked at, because the
    # only lawful way one of these is filled is from a resolver output that
    # the server binds — never from a slot the model proposed.
    "phone", "msisdn", "e164", "destination", "recipient", "address",
    "contact_id", "branch_id", "list_id", "tag_id", "segment_id",
    "campaign_id",
)

#: Namespaces a model may name an operation in. Membership here buys nothing
#: on its own — the operation still has to exist in the trusted catalog — it
#: only bounds what is worth looking up.
TRUSTED_OPERATION_NAMESPACES = ("slack.", "contacts.")

#: Identifier namespaces that are always resolver output. A model that emits
#: one has either guessed or replayed something it saw; both must fail here
#: rather than at a store that would happily accept a well-formed identifier.
_RESOLVED_IDENTIFIER = re.compile(
    r"^(?:contact|address|branch|list|tag|segment|campaign):",
    re.IGNORECASE,
)
#: A channel-qualified destination, the form Twilio and WhatsApp both use.
_CHANNEL_DESTINATION = re.compile(
    r"^(?:whatsapp|sms|mms|tel|voice|fax|sip):", re.IGNORECASE,
)
#: One mailbox and nothing else. Anchored, so a Slack handle (``@maria``) and
#: a message body that happens to mention an address both pass untouched — the
#: rule is about a scalar that *is* a destination, not one that contains one.
_MAILBOX = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_DIALLING_SEPARATORS = " \t-(). ‐‑‒–—"


def _looks_like_a_telephone_number(value):
    """Whether this scalar is a dialable number rather than prose.

    Anchored on the whole value on purpose. A draft that says "llámame al
    +34600111222" is a message body and must still reach Slack; a slot whose
    entire value is those digits is a destination and must not reach anything.

    Two thresholds, because the leading plus is itself a claim: with it, seven
    digits is already an international number. Without it, nine is the point
    below which ordinary scalars — years, quantities, a compacted ISO date —
    stop being distinguishable from a national subscriber number.
    """
    text = str(value).strip()
    plus = text.startswith("+")
    digits = text[1:] if plus else text
    for separator in _DIALLING_SEPARATORS:
        digits = digits.replace(separator, "")
    if not digits.isdigit():
        return False
    return len(digits) >= (7 if plus else 9) and len(digits) <= 15


def _authority_free_name(value):
    normalized = str(value or "").strip().casefold()
    if not normalized or any(marker in normalized for marker in _AUTHORITY_FIELD_MARKERS):
        raise ValueError("Slack interpretation fields may not contain authority")
    return normalized


def _authority_free_scalar(value):
    """Refuse every scalar a model could turn into a destination.

    The original rule covered provider identifiers, where invention fails
    harmlessly: a hallucinated Slack channel id matches nothing and the
    provider says so. A hallucinated telephone number is different in kind —
    it is syntactically valid, it belongs to somebody, the message arrives,
    and it is billed. So the identifiers that address a person are refused
    here on the same footing, leaving a resolver output as the only path from
    natural language to a destination.
    """
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise ValueError("Slack provider identifiers are not model input")
        if _SLACK_PROVIDER_ID.match(normalized.lstrip("#@")):
            raise ValueError("Slack provider identifiers are not model input")
        if _RESOLVED_IDENTIFIER.match(normalized):
            raise ValueError("resolved identifiers are not model input")
        if (
            _CHANNEL_DESTINATION.match(normalized)
            or _MAILBOX.match(normalized)
            or _looks_like_a_telephone_number(normalized)
        ):
            raise ValueError("destinations are not model input")
        return normalized
    return value


SlackInterpretationScalar = Union[str, int, float, bool]


class SlackOperationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("operation_id")
    @classmethod
    def validate_operation_id(cls, value):
        value = str(value or "").strip()
        if not value.startswith(TRUSTED_OPERATION_NAMESPACES):
            raise ValueError("operation_id must use a trusted namespace")
        return value


class SlackInterpretationSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: SlackInterpretationScalar
    provenance: Literal["current_turn", "conversation", "default"]
    operation_index: Optional[int] = Field(default=None, ge=0)

    _validate_name = field_validator("name")(_authority_free_name)
    _validate_value = field_validator("value")(_authority_free_scalar)


class SlackInterpretationCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: str
    replacement: SlackInterpretationScalar
    provenance: Literal["current_turn", "conversation"]
    operation_index: Optional[int] = Field(default=None, ge=0)

    _validate_slot = field_validator("slot")(_authority_free_name)
    _validate_replacement = field_validator("replacement")(
        _authority_free_scalar
    )


class SlackOperationDependency(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_index: int = Field(ge=0)
    depends_on_index: int = Field(ge=0)


class SlackInterpretationBlocker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    field: str
    question: str

    _validate_kind = field_validator("kind")(_authority_free_name)
    _validate_field = field_validator("field")(_authority_free_name)


class SlackInterpretation(BaseModel):
    """Authority-free model proposal grounded later by the operation registry."""

    model_config = ConfigDict(extra="forbid")

    operations: List[SlackOperationCandidate] = Field(
        default_factory=list, max_length=10,
    )
    slots: List[SlackInterpretationSlot] = Field(
        default_factory=list, max_length=30,
    )
    corrections: List[SlackInterpretationCorrection] = Field(
        default_factory=list, max_length=20,
    )
    dependencies: List[SlackOperationDependency] = Field(
        default_factory=list, max_length=45,
    )
    blockers: List[SlackInterpretationBlocker] = Field(
        default_factory=list, max_length=10,
    )
    locale: Literal["es", "en", "mixed"]
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_dependency_graph(self):
        size = len(self.operations)
        for slot in self.slots:
            if slot.operation_index is not None and slot.operation_index >= size:
                raise ValueError("slot operation index is invalid")
        for correction in self.corrections:
            if (
                correction.operation_index is not None
                and correction.operation_index >= size
            ):
                raise ValueError("correction operation index is invalid")
        for dependency in self.dependencies:
            if (
                dependency.operation_index >= size
                or dependency.depends_on_index >= size
                or dependency.operation_index == dependency.depends_on_index
            ):
                raise ValueError("operation dependency is invalid")
        return self


class WorkflowPlanStep(BaseModel):
    step_id: str
    capability_id: str
    capability_version: str
    connection_id: Optional[str] = None
    descriptor_snapshot_hash: str
    input: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[str] = Field(default_factory=list)
    agent_offer_id: Optional[str] = None


class WorkflowPlanDraft(BaseModel):
    tenant_id: str
    goal: str
    steps: List[WorkflowPlanStep]
    blockers: List[Dict[str, Any]] = Field(default_factory=list)


class BlockingNeed(BaseModel):
    kind: str
    field: str
    question: str
    step_id: Optional[str] = None


class GroundedCitation(BaseModel):
    """Minimized provider evidence safe to retain with a presentation."""

    citation_id: str
    channel_id: str
    message_ts: str
    permalink: str
    author_label: Optional[str] = None
    occurred_at: Optional[str] = None
    excerpt: Optional[str] = None
    excerpt_hash: Optional[str] = None


class ConversationPresentation(BaseModel):
    locale: str
    answer: str
    citations: List[GroundedCitation] = Field(default_factory=list)
    partial: bool = False
    partial_reason: Optional[str] = None


class ConciergeConversationState(BaseModel):
    """Server-authoritative working set for one Concierge modal session."""

    conversation_id: str
    tenant_id: str
    principal_id: str
    status: str = "interpreting"
    state_version: int = 1
    locale: Optional[str] = None
    operation: Optional[str] = None
    operation_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    known_inputs: Dict[str, Any] = Field(default_factory=dict)
    slot_state: List[Dict[str, Any]] = Field(default_factory=list)
    corrections: List[Dict[str, Any]] = Field(default_factory=list)
    dependencies: List[Dict[str, Any]] = Field(default_factory=list)
    blockers: List[Dict[str, Any]] = Field(default_factory=list)
    effect_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    entity_refs: List[Dict[str, Any]] = Field(default_factory=list)
    active_connection: Optional[Dict[str, Any]] = None
    active_channel: Optional[Dict[str, Any]] = None
    active_person: Optional[Dict[str, Any]] = None
    active_thread: Optional[Dict[str, Any]] = None
    active_message: Optional[Dict[str, Any]] = None
    active_file: Optional[Dict[str, Any]] = None
    active_reaction: Optional[Dict[str, Any]] = None
    read_period: Optional[Dict[str, Any]] = None
    pending_draft: Optional[Dict[str, Any]] = None
    workflow_run_id: Optional[str] = None
    workflow_revision_id: Optional[str] = None
    blocking_need: Optional[BlockingNeed] = None
    presentation: Optional[ConversationPresentation] = None
    created_at: int
    updated_at: int
    expires_at: int
