from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

from app.core.config import settings
from app.schemas.recommendations import RequirementProfile
from app.services.llm_client import KnowledgePlan


class SearchAndKnowledgeAgent:
    """Let the LLM plan retrieval, then execute local RAG and optional live search."""

    name = "SearchAndKnowledgeAgent"

    def __init__(self, client: Any, brain: Any, retriever: Any) -> None:
        self.client = client
        self.brain = brain
        self.retriever = retriever
        self.rag_tool = StructuredTool.from_function(
            func=retriever.retrieve,
            name="local_hardware_rag",
            description="Retrieve traceable component specs and prices from the local hardware catalog.",
        )
        self.web_tool = StructuredTool.from_function(
            func=client.search_hardware,
            name="serpapi_hardware_search",
            description="Optionally search current web prices when local evidence is insufficient.",
        )

    def run(self, profile: RequirementProfile) -> tuple[dict[str, Any], dict[str, Any]]:
        response = self.brain.invoke_agent(
            self.name,
            {
                "phase": "plan",
                "task": (
                    "Plan an evidence retrieval query for a PC build. The local RAG tool is mandatory. "
                    "Write a focused bilingual Chinese/English query containing the workload, budget, "
                    "resolution, constraints, and relevant hardware categories. Request web search only "
                    "when current market evidence is genuinely necessary; local RAG remains primary."
                ),
                "profile": profile.model_dump(),
                "available_tools": ["local_hardware_rag", "serpapi_hardware_search"],
                "tool_policy": {
                    "local_hardware_rag": "always execute",
                    "serpapi_hardware_search": (
                        "execute only when requested by the model, configured, and enabled by policy"
                    ),
                },
            },
            KnowledgePlan,
        )
        if response.get("status") != "success":
            return {}, response

        plan = response.get("result", {})
        query = str(plan.get("query") or "").strip()
        if not query:
            failed = dict(response)
            failed.update(status="failed", error="Knowledge planner returned an empty query")
            return {}, failed

        rag_result = self.rag_tool.invoke({"query": query, "top_k": settings.rag_top_k})
        web_requested = bool(plan.get("use_web_search"))
        web_allowed = (
            web_requested
            and settings.live_search_enabled
            and getattr(self.client, "is_configured", True)
        )
        if web_allowed:
            web_result = self.web_tool.invoke({"profile": profile, "query": query})
        else:
            reason = "not requested by AI"
            if web_requested and not settings.live_search_enabled:
                reason = "disabled by live-search-enabled policy"
            elif web_requested and not getattr(self.client, "is_configured", True):
                reason = "SerpAPI is not configured"
            web_result = {
                "status": "skipped",
                "provider": "serpapi",
                "result_count": 0,
                "results": [],
                "error": reason,
            }

        rag_ok = rag_result.get("status") == "success"
        web_ok = web_result.get("status") == "success"
        results = self._merge_results(
            rag_result.get("results", []) if rag_ok else [],
            web_result.get("results", []) if web_ok else [],
        )
        status = "success" if results and (rag_ok or web_ok) else "failed"
        result = {
            "status": status,
            "provider": "hybrid-rag",
            "query": query,
            "result_count": len(results),
            "results": results,
            "rag": {key: value for key, value in rag_result.items() if key != "results"},
            "web": {key: value for key, value in web_result.items() if key != "results"},
            "error": None if status == "success" else self._combined_error(rag_result, web_result),
        }
        response["events"] = [
            {
                "phase": "plan",
                "name": "deepseek",
                "summary": plan.get("summary", "Knowledge retrieval planned"),
                "query": query,
                "web_search_requested": web_requested,
            },
            {
                "phase": "tool",
                "name": "local_rag_retrieval",
                "summary": f"Local RAG returned {rag_result.get('result_count', 0)} records",
                "status": rag_result.get("status"),
                "retrieval_mode": rag_result.get("retrieval_mode"),
                "catalog_count": rag_result.get("catalog_count", 0),
            },
            {
                "phase": "tool",
                "name": "serpapi_hardware_search",
                "summary": (
                    f"SerpAPI returned {web_result.get('result_count', 0)} records"
                    if web_ok
                    else f"SerpAPI skipped: {web_result.get('error', 'not needed')}"
                ),
                "status": web_result.get("status"),
            },
        ]
        return result, response

    @staticmethod
    def _merge_results(local: list[dict[str, Any]], web: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in [*local, *web]:
            key = str(item.get("link") or item.get("title") or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
        return merged[:24]

    @staticmethod
    def _combined_error(rag: dict[str, Any], web: dict[str, Any]) -> str:
        return "; ".join(
            value
            for value in [rag.get("error"), web.get("error")]
            if value and "not requested" not in value
        ) or "No usable knowledge evidence was retrieved"
