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
)


def _authority_free_name(value):
    normalized = str(value or "").strip().casefold()
    if not normalized or any(marker in normalized for marker in _AUTHORITY_FIELD_MARKERS):
        raise ValueError("Slack interpretation fields may not contain authority")
    return normalized


def _authority_free_scalar(value):
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized or _SLACK_PROVIDER_ID.match(normalized.lstrip("#@")):
            raise ValueError("Slack provider identifiers are not model input")
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
        if not value.startswith("slack."):
            raise ValueError("operation_id must use the Slack namespace")
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
