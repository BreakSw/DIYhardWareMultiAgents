from __future__ import annotations

from typing import Any

from app.schemas.recommendations import RecommendationRequest, RequirementProfile
from app.services.llm_client import AgentInsight
from app.services.requirement_parser import RequirementParser


class BudgetParsingAgent:
    name = "BudgetParsingAgent"

    def __init__(self, parser: RequirementParser, brain: Any) -> None:
        self.parser = parser
        self.brain = brain

    def run(self, request: RecommendationRequest) -> tuple[RequirementProfile, list[dict[str, Any]], list[dict[str, Any]]]:
        planner = self.brain.invoke_agent(
            self.name,
            {
                "phase": "plan",
                "task": "定位预算证据，判断是精确值、区间、上限还是下限。不得凭空补充价格上限。",
                "user_text": request.text,
                "available_tools": [
                    "parse_budget_constraint",
                    "normalize_budget_unit",
                    "validate_budget_evidence",
                ],
            },
            AgentInsight,
        )

        profile = self.parser.parse(request.text)
        if request.budget is not None:
            profile.budget = request.budget
            profile.budget_min = request.budget
            profile.budget_max = request.budget
            profile.budget_mode = "exact"
            profile.budget_evidence = f"API budget={request.budget}"
            profile.budget_explicit = True

        tool_event = {
            "phase": "tool",
            "name": "parse_budget_constraint",
            "input": {"text_excerpt": request.text[:160]},
            "output": {
                "budget_mode": profile.budget_mode,
                "budget_min": profile.budget_min,
                "budget_max": profile.budget_max,
                "target_budget": profile.budget,
                "evidence": profile.budget_evidence,
                "explicit": profile.budget_explicit,
            },
            "summary": "确定性预算工具已完成单位归一化与边界识别",
        }

        reflection = self.brain.invoke_agent(
            self.name,
            {
                "phase": "reflection",
                "task": "核对工具结果是否被原文证据直接支持。不得修改工具数值，只报告歧义或风险。",
                "user_text": request.text,
                "tool_result": tool_event["output"],
            },
            AgentInsight,
        )
        events = [
            self._ai_event("plan", planner, "AI 制定预算解析计划"),
            tool_event,
            self._ai_event("reflection", reflection, "AI 复核预算证据与边界"),
        ]
        return profile, events, [planner, reflection]

    @staticmethod
    def _ai_event(phase: str, response: dict[str, Any], summary: str) -> dict[str, Any]:
        result = response.get("result", {})
        return {
            "phase": phase,
            "name": "deepseek",
            "summary": result.get("summary") or summary,
            "observations": result.get("observations", []),
            "status": response.get("status", "failed"),
            "model": response.get("model"),
            "usage": response.get("usage", {}),
            "error": response.get("error"),
        }