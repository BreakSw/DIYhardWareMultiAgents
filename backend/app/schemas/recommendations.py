from __future__ import annotations

from typing import Any, Literal, Optional, Self

from pydantic import BaseModel, Field, model_validator


class RequirementRequest(BaseModel):
    text: str = Field(min_length=2, max_length=2000)


class RequirementProfile(BaseModel):
    budget: int = 6000
    budget_min: int = 6000
    budget_max: Optional[int] = 6000
    budget_mode: str = "exact"
    budget_evidence: str = ""
    resolution: str = "2K"
    usage: str = "综合使用"
    case_size: str = "ATX"
    include_peripherals: bool = False
    budget_explicit: bool = False
    usage_explicit: bool = False
    peripherals_explicit: bool = False
    allow_under_budget: bool = False
    owned_parts: dict[str, str] = Field(default_factory=dict)
    impossible_reason: Optional[str] = None
    assumptions: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class RecommendationRequest(BaseModel):
    text: str = Field(min_length=2, max_length=2000)
    budget: Optional[int] = Field(default=None, ge=1000, le=200000)
    resolution: Optional[str] = None
    usage: Optional[str] = None
    case_size: Optional[str] = None
    context_messages: list[ConversationMessage] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def validate_context_content_length(self) -> Self:
        if sum(len(message.content) for message in self.context_messages) > 12_000:
            raise ValueError("context message content exceeds 12,000 characters")
        return self


class CompatibilityRequest(BaseModel):
    parts: list[dict[str, Any]] = Field(min_length=1)


class RecommendationSummary(BaseModel):
    task_id: str
    status: str
    score: int
    total_price: int
    profile: RequirementProfile
    parts: list[dict[str, Any]]
    checks: list[dict[str, Any]]
    alternatives: list[dict[str, Any]]
    rationale: list[str]
    provenance: dict[str, Any]
    sources: list[dict[str, Any]]
    budget_check: dict[str, Any]
    agent_runs: list[dict[str, Any]]
    risks: list[str] = Field(default_factory=list)


class TaskStatus(BaseModel):
    task_id: str
    status: str
    progress: int
    current_agent: Optional[str] = None
    degraded_reason: Optional[str] = None
    follow_up_questions: list[str] = Field(default_factory=list)
    agent_runs: list[dict[str, Any]] = Field(default_factory=list)
