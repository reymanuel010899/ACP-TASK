"""Typed planner output. These models contain no provider authority."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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
    locale: Optional[str] = None
    operation: Optional[str] = None
    active_connection: Optional[Dict[str, Any]] = None
    active_channel: Optional[Dict[str, Any]] = None
    active_person: Optional[Dict[str, Any]] = None
    active_thread: Optional[Dict[str, Any]] = None
    read_period: Optional[Dict[str, Any]] = None
    pending_draft: Optional[Dict[str, Any]] = None
    workflow_run_id: Optional[str] = None
    workflow_revision_id: Optional[str] = None
    blocking_need: Optional[BlockingNeed] = None
    presentation: Optional[ConversationPresentation] = None
    created_at: int
    updated_at: int
    expires_at: int
