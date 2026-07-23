from __future__ import annotations

from typing import Any, TypedDict

from app.schemas.recommendations import RecommendationRequest, RequirementProfile

AGENT_NAMES = [
    "SupervisorAgent",
    "IntentClassificationAgent",
    "BudgetParsingAgent",
    "RequirementAgent",
    "SearchAndKnowledgeAgent",
    "HardwareSelectionAgent",
    "CompatibilityAndPricingAgent",
    "ReportAgent",
]


class AgentState(TypedDict, total=False):
    task_id: str
    request: RecommendationRequest
    status: str
    progress: int
    current_agent: str | None
    profile: RequirementProfile
    search_result: dict[str, Any]
    selection_payload: dict[str, Any]
    parts: list[dict[str, Any]]
    evaluation: dict[str, Any]
    result: dict[str, Any]
    agent_runs: list[dict[str, Any]]
    follow_up_questions: list[str]
    degraded_reason: str | None
    selection_attempts: int
    revision_feedback: str | None
    route: str
    ai_calls: list[dict[str, Any]]
    ai_usage: dict[str, int]
    llm_meta: dict[str, Any]
    started_at: dict[str, float]
    intent_classification: dict[str, Any]


