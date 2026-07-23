from __future__ import annotations

import copy
from decimal import Decimal, InvalidOperation
from typing import Any

from app.agents.state import AgentState
from app.services.llm_client import ReportNarrative


class ReportAgent:
    name = "ReportAgent"

    def __init__(self, brain: Any) -> None:
        self.brain = brain

    def run(self, state: AgentState) -> tuple[dict[str, Any], dict[str, Any]]:
        profile = state["profile"]
        evaluation = state["evaluation"]
        payload = state.get("selection_payload", {})
        search = state.get("search_result", {})
        ai_response = self.brain.invoke_agent(
            self.name,
            {
                "task": (
                    "只基于已通过硬校验的方案生成简洁购买理由、备选方向和风险。"
                    "不得更换部件、价格或校验结论。"
                ),
                "profile": profile.model_dump(),
                "parts": state["parts"],
                "evaluation": evaluation,
                "sources": search.get("results", [])[:5],
            },
            ReportNarrative,
        )
        if ai_response.get("status") != "success":
            return {}, ai_response

        narrative = ai_response.get("result", {})
        sources = [
            {key: item.get(key) for key in ["title", "link", "source", "price"]}
            for item in search.get("results", [])[:5]
        ]
        rationale = list(narrative["rationale"])
        if profile.allow_under_budget and evaluation["budget_check"]["estimated_total"] < profile.budget_min:
            rationale.append("用户明确允许不花满预算，因此低于区间下限仍可发布。")
        enriched_parts = self._enrich_parts(state["parts"], search.get("results", []))
        result = {
            "task_id": state["task_id"],
            "status": "completed",
            "score": evaluation["score"],
            "total_price": evaluation["budget_check"]["estimated_total"],
            "profile": profile.model_dump(),
            "parts": enriched_parts,
            "checks": evaluation["checks"],
            "alternatives": narrative.get("alternatives", []),
            "rationale": rationale,
            "budget_check": evaluation["budget_check"],
            "ai_usage": state.get("ai_usage", {}),
            "provenance": {
                "mode": "live",
                "parser": {
                    "status": "success",
                    "engine": "deterministic+deepseek",
                    "budget_min": profile.budget_min,
                    "budget_max": profile.budget_max,
                    "target_budget": profile.budget,
                },
                "search": {key: value for key, value in search.items() if key != "results"},
                "llm": {
                    "status": "success",
                    "provider": "deepseek",
                    "model": ai_response.get("model"),
                    "agent_call_count": len(state.get("ai_calls", [])) + 1,
                },
                "build_source": "deepseek_live",
            },
            "sources": sources,
            "risks": narrative.get("risks") or [],
        }
        return result, ai_response

    @classmethod
    def _enrich_parts(
        cls,
        parts: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for original in parts:
            part = copy.deepcopy(original)
            category_evidence = [
                item for item in evidence if item.get("category") == part.get("category")
            ]
            prices = [cls._price(item.get("price")) for item in category_evidence]
            prices = [price for price in prices if price is not None]
            if prices:
                part["price_range"] = {
                    "min": int(min(prices)),
                    "max": int(max(prices)),
                    "currency": "CNY",
                    "sample_count": len(prices),
                }
            if category_evidence:
                best = category_evidence[0]
                part["evidence"] = {
                    "title": best.get("title"),
                    "link": best.get("link"),
                    "source": best.get("source"),
                    "retrieval_score": best.get("retrieval_score"),
                }
            enriched.append(part)
        return enriched

    @staticmethod
    def _price(value: Any) -> Decimal | None:
        try:
            return Decimal(str(value).replace(",", ""))
        except (InvalidOperation, TypeError, ValueError):
            return None
