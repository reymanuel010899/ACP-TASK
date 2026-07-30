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
