from __future__ import annotations

import copy
import threading
from typing import Any
from uuid import uuid4

from app.agents.state import AGENT_NAMES, AgentState
from app.agents.workflow import LangGraphWorkflow
from app.repositories.catalog import CatalogRepository, InMemoryTaskRepository
from app.schemas.recommendations import RecommendationRequest, RequirementProfile
from app.services.llm_client import DeepSeekClient
from app.services.requirement_parser import RequirementParser
from app.services.search_client import SerpApiClient
from app.services.rag_retriever import build_catalog_rag_retriever


class RecommendationService:
    def __init__(
        self,
        catalog: CatalogRepository,
        tasks: InMemoryTaskRepository,
        search_client: Any | None = None,
        llm_client: Any | None = None,
        rag_retriever: Any | None = None,
    ) -> None:
        self.catalog = catalog
        self.tasks = tasks
        self.parser = RequirementParser()
        self._lock = threading.RLock()
        self.workflow = LangGraphWorkflow(
            catalog,
            tasks,
            search_client or SerpApiClient(),
            llm_client or DeepSeekClient(),
            rag_retriever or build_catalog_rag_retriever(),
        )
        self.graph = self.workflow.graph

    def parse(self, text: str) -> RequirementProfile:
        return self.parser.parse(text)

    def create_task(self, request: RecommendationRequest) -> dict[str, Any]:
        task_id = f"task_{uuid4().hex[:12]}"
        task = {
            "task_id": task_id,
            "status": "queued",
            "progress": 0,
            "current_agent": None,
            "degraded_reason": None,
            "follow_up_questions": [],
            "request": request.model_dump(),
            "result": None,
            "ai_usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "agent_runs": [self._empty_run(name) for name in AGENT_NAMES],
        }
        with self._lock:
            self.tasks.save(task_id, task)
        return {"task_id": task_id, "status": "queued"}

    def run_task(self, task_id: str) -> None:
        task = self.tasks.get(task_id)
        if task is None:
            return
        request = RecommendationRequest.model_validate(task["request"])
        initial: AgentState = {
            "task_id": task_id,
            "request": request,
            "status": "queued",
            "progress": 0,
            "current_agent": None,
            "agent_runs": copy.deepcopy(task["agent_runs"]),
            "follow_up_questions": [],
            "degraded_reason": None,
            "selection_attempts": 0,
            "revision_feedback": None,
            "route": "continue",
            "ai_calls": [],
            "ai_usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "started_at": {},
        }
        try:
            final = self.workflow.invoke(initial)
            status = final.get("status", "failed")
            result = final.get("result")
            if status == "degraded" and result is None:
                result = self._degraded_result(task_id, final)
            if result is not None:
                result["agent_runs"] = self._public_runs(final["agent_runs"])
            self._save_final(task_id, final, result)
        except Exception as exc:
            self._save_failure(task_id, exc)

    def recommend(self, request: RecommendationRequest) -> dict[str, Any]:
        created = self.create_task(request)
        self.run_task(created["task_id"])
        task = self.tasks.get(created["task_id"])
        return task.get("result") or self.get_status(created["task_id"])

    def get_status(self, task_id: str) -> dict[str, Any] | None:
        task = self.tasks.get(task_id)
        if task is None:
            return None
        return {
            key: copy.deepcopy(task.get(key))
            for key in [
                "task_id",
                "status",
                "progress",
                "current_agent",
                "degraded_reason",
                "follow_up_questions",
                "agent_runs",
                "ai_usage",
            ]
        }

    def get_result(self, task_id: str) -> dict[str, Any] | None:
        task = self.tasks.get(task_id)
        return None if task is None else copy.deepcopy(task.get("result"))

    def get_trace(self, task_id: str) -> dict[str, Any] | None:
        status = self.get_status(task_id)
        if status is None:
            return None
        return {
            "task_id": task_id,
            "ai_usage": status["ai_usage"],
            "events": status["agent_runs"],
        }

    @staticmethod
    def _empty_run(name: str) -> dict[str, Any]:
        return {
            "agent_name": name,
            "status": "pending",
            "iterations": 0,
            "input_summary": "",
            "output_summary": "",
            "latency_ms": 0,
            "tool_calls": [],
            "error": None,
            "ai_call": {
                "status": "pending",
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            },
        }

    def _save_final(
        self,
        task_id: str,
        final: AgentState,
        result: dict[str, Any] | None,
    ) -> None:
        with self._lock:
            task = self.tasks.get(task_id) or {"task_id": task_id}
            task.update(
                status=final.get("status", "failed"),
                progress=100,
                current_agent=None,
                degraded_reason=final.get("degraded_reason"),
                follow_up_questions=final.get("follow_up_questions", []),
                agent_runs=self._public_runs(final["agent_runs"]),
                ai_usage=copy.deepcopy(final.get("ai_usage", {})),
                result=result,
            )
            self.tasks.save(task_id, task)

    def _save_failure(self, task_id: str, exc: Exception) -> None:
        with self._lock:
            task = self.tasks.get(task_id)
            if task is None:
                return
            runs = task["agent_runs"]
            current = task.get("current_agent")
            for run in runs:
                if run["agent_name"] == current and run["status"] == "running":
                    run.update(
                        status="failed",
                        error=str(exc)[:500],
                        output_summary="节点执行异常",
                    )
                elif run["status"] == "pending":
                    run.update(status="skipped", output_summary="上游节点执行失败")
            task.update(
                status="failed",
                progress=100,
                current_agent=None,
                degraded_reason=f"编排执行失败：{str(exc)[:300]}",
                result=None,
            )
            self.tasks.save(task_id, task)

    @staticmethod
    def _public_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {key: value for key, value in run.items() if not key.startswith("_")}
            for run in runs
        ]

    @staticmethod
    def _degraded_result(task_id: str, state: AgentState) -> dict[str, Any]:
        profile = state.get("profile")
        evaluation = state.get("evaluation", {})
        budget_check = evaluation.get(
            "budget_check",
            {
                "budget_min": profile.budget_min if profile else 0,
                "budget_max": profile.budget_max if profile else 0,
                "target_budget": profile.budget if profile else 0,
                "estimated_total": 0,
                "delta_from_target": -(profile.budget if profile else 0),
                "utilization_rate": 0,
                "passed": False,
                "allow_under_budget": profile.allow_under_budget if profile else False,
            },
        )
        return {
            "task_id": task_id,
            "status": "degraded",
            "score": min(60, evaluation.get("score", 0)),
            "total_price": 0,
            "profile": profile.model_dump() if profile else {},
            "parts": [],
            "checks": evaluation.get("checks", []),
            "alternatives": [],
            "rationale": [state.get("degraded_reason") or "没有可安全发布的方案。"],
            "budget_check": budget_check,
            "ai_usage": copy.deepcopy(state.get("ai_usage", {})),
            "provenance": {
                "mode": "ai_failed",
                "parser": {"status": "success", "engine": "deterministic+deepseek"},
                "search": {
                    key: value
                    for key, value in state.get("search_result", {}).items()
                    if key != "results"
                },
                "llm": {
                    "status": "failed",
                    "provider": "deepseek",
                    "agent_call_count": len(state.get("ai_calls", [])),
                    "error": state.get("degraded_reason"),
                },
                "build_source": "none",
            },
            "sources": [],
            "risks": ["AI 链路或硬校验未完整通过，当前结果不可作为购买清单"],
        }
