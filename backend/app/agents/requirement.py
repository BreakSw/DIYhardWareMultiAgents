from __future__ import annotations

from typing import Any

from app.schemas.recommendations import RecommendationRequest, RequirementProfile
from app.services.llm_client import RequirementAnalysis
from app.services.requirement_parser import RequirementParser


class RequirementAgent:
    """AI semantic planner followed by a deterministic profile merge tool."""

    name = "RequirementAgent"

    def __init__(self, parser: RequirementParser, brain: Any) -> None:
        self.parser = parser
        self.brain = brain

    def run(
        self,
        request: RecommendationRequest,
        profile: RequirementProfile | None = None,
    ) -> tuple[RequirementProfile, list[str], dict[str, Any]]:
        profile = profile or self.parser.parse(request.text)
        payload = self._analysis_payload(request, profile)
        response = self.brain.invoke_agent(self.name, payload, RequirementAnalysis)
        attempts = [response]
        if response.get("status") != "success":
            response["attempt_responses"] = attempts
            return profile, [], response

        analysis = RequirementAnalysis.model_validate(response.get("result", {}))
        if self._fabricates_unknown_budget(profile, analysis):
            response = self.brain.invoke_agent(
                self.name,
                {
                    **payload,
                    "phase": "reflection",
                    "task": (
                        "Correct the previous analysis. The deterministic budget tool found no "
                        "user-provided budget, so partial_answer must not state or imply any "
                        "specific remaining or total budget. Preserve confirmed requirements and "
                        "ask for the missing budget."
                    ),
                    "previous_analysis": analysis.model_dump(),
                    "validation_error": "partial_answer fabricated a budget amount",
                },
                RequirementAnalysis,
            )
            attempts.append(response)
            if response.get("status") != "success":
                response["attempt_responses"] = attempts
                return profile, [], response
            analysis = RequirementAnalysis.model_validate(response.get("result", {}))
            if self._fabricates_unknown_budget(profile, analysis):
                response = {
                    **response,
                    "status": "failed",
                    "error": "需求模型在预算未知时生成了没有依据的预算金额",
                    "attempt_responses": attempts,
                }
                return profile, [], response

        response["attempt_responses"] = attempts
        self._merge_semantic_requirements(profile, request, analysis)
        questions = self._validate_completeness(profile, request, analysis)
        response["events"] = [
            {
                "phase": "plan",
                "name": "deepseek",
                "summary": analysis.summary,
                "confidence": analysis.confidence,
            },
            {
                "phase": "tool",
                "name": "merge_semantic_requirements",
                "summary": "AI semantic output merged without changing deterministic budget fields",
                "output": {
                    "usage": profile.usage,
                    "resolution": profile.resolution,
                    "include_peripherals": profile.include_peripherals,
                    "owned_parts": profile.owned_parts,
                    "constraints": profile.notes,
                },
            },
            {
                "phase": "decision",
                "name": "validate_requirement_completeness",
                "summary": "clarification required" if questions else "requirements are publishable",
                "questions": questions,
            },
        ]
        return profile, questions, response

    def _analysis_payload(
        self,
        request: RecommendationRequest,
        profile: RequirementProfile,
    ) -> dict[str, Any]:
        budget_values = {
            "minimum": profile.budget_min,
            "maximum": profile.budget_max,
            "target": profile.budget,
        }
        if not profile.budget_explicit:
            budget_values = {"minimum": None, "maximum": None, "target": None}
        return {
            "phase": "plan",
            "task": (
                "Understand the user's semantic PC requirements. Recognize any game, "
                "software, workload, brand, existing component, peripheral scope, form "
                "factor, noise, appearance, performance preference, and whether the user "
                "explicitly allows spending below the budget floor from meaning, not "
                "from a fixed title whitelist. Treat the budget handoff as immutable. "
                "Ask only when missing information would materially change the build."
            ),
            "user_text": request.text,
            "conversation_context": [
                message.model_dump() for message in request.context_messages
            ],
            "budget_handoff": {
                "mode": profile.budget_mode if profile.budget_explicit else "unknown",
                **budget_values,
                "evidence": profile.budget_evidence,
                "explicit": profile.budget_explicit,
            },
            "available_tools": [
                "merge_semantic_requirements",
                "validate_requirement_completeness",
            ],
            "response_policy": (
                "When clarification is needed, partial_answer must first summarize confirmed "
                "requirements and provide safe directional advice, then questions must ask only "
                "for missing information that materially changes the build. Do not fabricate "
                "a purchasable part list, current prices, or any budget amount. If "
                "budget_handoff.explicit is false, all budget values are unknown and no hidden "
                "default may be mentioned or used."
            ),
        }

    def _fabricates_unknown_budget(
        self,
        profile: RequirementProfile,
        analysis: RequirementAnalysis,
    ) -> bool:
        if profile.budget_explicit or not analysis.partial_answer.strip():
            return False
        return self.parser.parse_budget_constraint(analysis.partial_answer)[2]

    @staticmethod
    def _merge_semantic_requirements(
        profile: RequirementProfile,
        request: RecommendationRequest,
        analysis: RequirementAnalysis,
    ) -> None:
        profile.usage = request.usage or analysis.usage
        profile.usage_explicit = bool(request.usage or analysis.usage_explicit)
        profile.resolution = request.resolution or analysis.resolution
        profile.case_size = request.case_size or analysis.case_size
        profile.include_peripherals = analysis.include_peripherals
        profile.peripherals_explicit = analysis.peripherals_explicit
        profile.allow_under_budget = analysis.allow_under_budget
        profile.owned_parts = dict(analysis.owned_parts)
        profile.notes = list(dict.fromkeys([*profile.notes, *analysis.constraints]))
        profile.assumptions = list(dict.fromkeys(analysis.assumptions))
        profile.impossible_reason = analysis.impossible_reason

    @staticmethod
    def _validate_completeness(
        profile: RequirementProfile,
        request: RecommendationRequest,
        analysis: RequirementAnalysis,
    ) -> list[str]:
        questions: list[str] = []
        if not profile.budget_explicit:
            questions.append("请提供主机或整套电脑的预算金额或区间。")
        if not profile.usage_explicit:
            questions.extend(analysis.questions or ["请说明这台电脑的主要用途。"])
        unresolved = set(analysis.missing_fields)
        if request.usage:
            unresolved.discard("usage")
        if request.resolution:
            unresolved.discard("resolution")
        if request.case_size:
            unresolved.discard("case_size")
        if analysis.needs_clarification and unresolved and profile.usage_explicit:
            questions.extend(analysis.questions)
        return list(dict.fromkeys(questions))
