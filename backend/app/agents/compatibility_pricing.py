from __future__ import annotations

from typing import Any

from app.schemas.recommendations import RequirementProfile
from app.services.compatibility import CompatibilityService
from app.services.llm_client import AgentInsight, ToolPlan


class CompatibilityAndPricingAgent:
    """AI-planned audit with deterministic, non-overridable validation tools."""

    name = "CompatibilityAndPricingAgent"

    def __init__(self, compatibility: CompatibilityService, brain: Any) -> None:
        self.compatibility = compatibility
        self.brain = brain

    def run(
        self, parts: list[dict[str, Any]], profile: RequirementProfile
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        mandatory_tools = [
            "check_component_completeness",
            "check_physical_and_electrical_compatibility",
            "calculate_purchase_total",
            "validate_budget_bounds",
        ]
        planner = self.brain.invoke_agent(
            self.name,
            {
                "phase": "plan",
                "task": (
                    "Plan the compatibility and pricing audit for this exact build. "
                    "Select the relevant tools and identify risks to inspect. Do not "
                    "calculate totals or invent pass/fail outcomes yourself."
                ),
                "profile": profile.model_dump(),
                "parts": parts,
                "available_tools": mandatory_tools,
                "mandatory_tools": mandatory_tools,
            },
            ToolPlan,
        )
        if planner.get("status") != "success":
            return {}, [], [planner]

        evaluation = self._execute_tools(parts, profile)
        review = self.brain.invoke_agent(
            self.name,
            {
                "phase": "reflection",
                "task": (
                    "Reflect on the deterministic tool outputs, explain concrete risks, "
                    "and provide actionable revision guidance. Never change a failed check "
                    "to passed and never alter the calculated total."
                ),
                "profile": profile.model_dump(),
                "parts": parts,
                "deterministic_evaluation": evaluation,
            },
            AgentInsight,
        )
        events = [
            {
                "phase": "plan",
                "name": "deepseek",
                "summary": planner.get("result", {}).get("summary", "AI audit plan"),
                "requested_tools": planner.get("result", {}).get("tool_calls", []),
            },
            {
                "phase": "tool",
                "name": "deterministic_hard_gates",
                "summary": "Mandatory validation tools executed",
                "tools": mandatory_tools,
                "output": evaluation,
            },
            {
                "phase": "reflection",
                "name": "deepseek",
                "summary": review.get("result", {}).get("summary", "AI audit reflection"),
                "observations": review.get("result", {}).get("observations", []),
                "risks": review.get("result", {}).get("risks", []),
            },
        ]
        return evaluation, events, [planner, review]

    def _execute_tools(
        self, parts: list[dict[str, Any]], profile: RequirementProfile
    ) -> dict[str, Any]:
        check_parts = list(parts)
        if "gpu" in profile.owned_parts:
            check_parts.append(
                {
                    "id": "owned-gpu",
                    "category": "gpu",
                    "name": profile.owned_parts["gpu"],
                    "price": 0,
                    "specs": {"length_mm": 300, "tdp": 250},
                }
            )

        checks = self.compatibility.check(check_parts)
        categories = {part.get("category") for part in parts}
        required = {"cpu", "motherboard", "memory", "storage", "psu", "cooler", "case"}
        if "gpu" not in profile.owned_parts:
            required.add("gpu")
        missing = sorted(required - categories)
        checks.insert(
            0,
            {
                "name": "Component completeness",
                "passed": not missing,
                "severity": "success" if not missing else "error",
                "detail": "Complete" if not missing else f"Missing: {', '.join(missing)}",
            },
        )
        if profile.include_peripherals:
            peripheral_missing = sorted({"monitor", "keyboard", "mouse"} - categories)
            checks.append(
                {
                    "name": "Peripheral scope",
                    "passed": not peripheral_missing,
                    "severity": "success" if not peripheral_missing else "error",
                    "detail": (
                        "Monitor, keyboard, and mouse included"
                        if not peripheral_missing
                        else f"Missing: {', '.join(peripheral_missing)}"
                    ),
                }
            )

        total = sum(int(part.get("price", 0)) for part in parts)
        within_ceiling = profile.budget_max is None or total <= profile.budget_max
        budget_passed = within_ceiling and (
            profile.allow_under_budget or total >= profile.budget_min
        )
        compatibility_passed = all(check.get("passed") for check in checks)
        publishable = budget_passed and compatibility_passed
        passed_checks = sum(1 for check in checks if check.get("passed"))
        score = min(98, 63 + passed_checks * 5 + (5 if budget_passed else 0))
        if not publishable:
            score = min(score, 60)
        return {
            "checks": checks,
            "compatibility_passed": compatibility_passed,
            "budget_check": {
                "budget_min": profile.budget_min,
                "budget_max": profile.budget_max,
                "target_budget": profile.budget,
                "estimated_total": total,
                "delta_from_target": total - profile.budget,
                "utilization_rate": round(total / profile.budget, 4) if profile.budget else 0,
                "passed": budget_passed,
                "allow_under_budget": profile.allow_under_budget,
            },
            "publishable": publishable,
            "score": score,
        }
