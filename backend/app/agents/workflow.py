from __future__ import annotations

import copy
import threading
import time
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.budget_parsing import BudgetParsingAgent
from app.agents.compatibility_pricing import CompatibilityAndPricingAgent
from app.agents.hardware_selection import HardwareSelectionAgent
from app.agents.intent_classification import IntentClassificationAgent
from app.agents.report import ReportAgent
from app.agents.requirement import RequirementAgent
from app.agents.search_knowledge import SearchAndKnowledgeAgent
from app.agents.state import AGENT_NAMES, AgentState
from app.agents.supervisor import SupervisorAgent
from app.repositories.catalog import CatalogRepository, InMemoryTaskRepository
from app.services.compatibility import CompatibilityService
from app.services.requirement_parser import RequirementParser


class LangGraphWorkflow:
    """Seven AI-assisted nodes with deterministic hard publication gates."""

    def __init__(
        self,
        catalog: CatalogRepository,
        tasks: InMemoryTaskRepository,
        search_client: Any,
        llm_client: Any,
        rag_retriever: Any,
    ) -> None:
        self.tasks = tasks
        self.lock = threading.RLock()
        self.supervisor = SupervisorAgent(llm_client)
        self.intent = IntentClassificationAgent(llm_client)
        self.budget = BudgetParsingAgent(RequirementParser(), llm_client)
        self.requirement = RequirementAgent(RequirementParser(), llm_client)
        self.search = SearchAndKnowledgeAgent(search_client, llm_client, rag_retriever)
        self.hardware = HardwareSelectionAgent(llm_client, catalog)
        self.compatibility = CompatibilityAndPricingAgent(CompatibilityService(), llm_client)
        self.report = ReportAgent(llm_client)
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(AgentState)
        builder.add_node("SupervisorAgent", self._supervisor_node)
        builder.add_node("IntentClassificationAgent", self._intent_node)
        builder.add_node("BudgetParsingAgent", self._budget_node)
        builder.add_node("RequirementAgent", self._requirement_node)
        builder.add_node("SearchAndKnowledgeAgent", self._search_node)
        builder.add_node("HardwareSelectionAgent", self._hardware_node)
        builder.add_node("CompatibilityAndPricingAgent", self._compatibility_node)
        builder.add_node("ReportAgent", self._report_node)
        builder.add_edge(START, "SupervisorAgent")
        builder.add_conditional_edges(
            "SupervisorAgent",
            lambda state: state["route"],
            {"continue": "IntentClassificationAgent", "stop": END},
        )
        builder.add_conditional_edges(
            "IntentClassificationAgent",
            lambda state: state["route"],
            {"continue": "BudgetParsingAgent", "stop": END},
        )
        builder.add_conditional_edges(
            "BudgetParsingAgent",
            lambda state: state["route"],
            {"continue": "RequirementAgent", "stop": END},
        )
        builder.add_conditional_edges(
            "RequirementAgent",
            lambda state: state["route"],
            {"continue": "SearchAndKnowledgeAgent", "stop": END},
        )
        builder.add_conditional_edges(
            "SearchAndKnowledgeAgent",
            lambda state: state["route"],
            {"continue": "HardwareSelectionAgent", "stop": END},
        )
        builder.add_conditional_edges(
            "HardwareSelectionAgent",
            lambda state: state["route"],
            {"continue": "CompatibilityAndPricingAgent", "stop": END},
        )
        builder.add_conditional_edges(
            "CompatibilityAndPricingAgent",
            lambda state: state["route"],
            {"retry": "HardwareSelectionAgent", "report": "ReportAgent", "stop": END},
        )
        builder.add_edge("ReportAgent", END)
        return builder.compile()

    def invoke(self, state: AgentState) -> AgentState:
        return self.graph.invoke(state, config={"recursion_limit": 12})

    def _supervisor_node(self, state: AgentState) -> dict[str, Any]:
        state = self._start(state, SupervisorAgent.name, "AI 监督员审阅任务并启动编排", 5)
        response = self.supervisor.run(state["request"].text)
        state = self._record_ai(state, SupervisorAgent.name, response)
        if response.get("status") != "success":
            return self._ai_failure(state, SupervisorAgent.name, BudgetParsingAgent.name, response)
        self._run(state, SupervisorAgent.name)["events"] = [
            {
                "phase": "plan",
                "name": "deepseek",
                "summary": response["result"].get("summary", "AI orchestration plan"),
                "observations": response["result"].get("observations", []),
            }
        ]
        state["route"] = "continue"
        return self._finish(
            state,
            SupervisorAgent.name,
            "completed",
            response["result"].get("summary", "监督规划完成"),
            tool_calls=["deepseek:supervisor"],
        )

    def _intent_node(self, state: AgentState) -> dict[str, Any]:
        state = self._start(
            state,
            IntentClassificationAgent.name,
            "DeepSeek semantically classifies whether the request belongs to PC building",
            10,
        )
        response = self.intent.run(state["request"].text)
        state = self._record_ai(state, IntentClassificationAgent.name, response)
        if response.get("status") != "success":
            return self._ai_failure(
                state,
                IntentClassificationAgent.name,
                BudgetParsingAgent.name,
                response,
            )

        decision = copy.deepcopy(response.get("result", {}))
        state["intent_classification"] = decision
        self._run(state, IntentClassificationAgent.name)["events"] = [
            {
                "phase": "classify",
                "name": "deepseek",
                "summary": decision.get("reason", "Intent classification completed"),
                "request_type": decision.get("request_type"),
                "confidence": decision.get("confidence"),
                "in_scope": decision.get("is_pc_build_request"),
            }
        ]
        state = self._finish(
            state,
            IntentClassificationAgent.name,
            "completed",
            (
                f"type={decision.get('request_type', 'unknown')}, "
                f"in_scope={bool(decision.get('is_pc_build_request'))}, "
                f"confidence={decision.get('confidence', 0)}"
            ),
            tool_calls=["deepseek:intent_classification"],
        )
        if not decision.get("is_pc_build_request"):
            message = "这个问题我不太了解，我们聊一些有关电脑装机、硬件选型或升级的问题吧。"
            state["status"] = "needs_clarification"
            state["follow_up_questions"] = [message]
            state["route"] = "stop"
            return self._skip_remaining(state, BudgetParsingAgent.name, "题外问题，工作流已停止")

        state["route"] = "continue"
        return state

    def _budget_node(self, state: AgentState) -> dict[str, Any]:
        state = self._start(
            state,
            BudgetParsingAgent.name,
            "AI plans budget parsing, deterministic tools execute, AI reflects",
            15,
        )
        profile, events, responses = self.budget.run(state["request"])
        state["profile"] = profile
        self._run(state, BudgetParsingAgent.name)["events"] = events
        for response in responses:
            state = self._record_ai(state, BudgetParsingAgent.name, response)
            if response.get("status") != "success":
                return self._ai_failure(
                    state,
                    BudgetParsingAgent.name,
                    RequirementAgent.name,
                    response,
                )
        state["route"] = "continue"
        maximum = "none" if profile.budget_max is None else str(profile.budget_max)
        return self._finish(
            state,
            BudgetParsingAgent.name,
            "completed",
            f"mode={profile.budget_mode}, min={profile.budget_min}, max={maximum}, evidence={profile.budget_evidence or 'none'}",
            tool_calls=[
                "deepseek:budget_plan",
                "parse_budget_constraint",
                "deepseek:budget_reflection",
            ],
            iterations=3,
        )

    def _requirement_node(self, state: AgentState) -> dict[str, Any]:
        state = self._start(state, RequirementAgent.name, state["request"].text, 28)
        profile, questions, response = self.requirement.run(
            state["request"], state.get("profile")
        )
        state["profile"] = profile
        state["follow_up_questions"] = questions
        state = self._record_ai(state, RequirementAgent.name, response)
        if response.get("events"):
            self._run(state, RequirementAgent.name)["events"] = copy.deepcopy(
                response["events"]
            )
        if response.get("status") != "success":
            return self._ai_failure(state, RequirementAgent.name, SearchAndKnowledgeAgent.name, response)
        if profile.impossible_reason:
            state["status"] = "degraded"
            state["degraded_reason"] = profile.impossible_reason
            state["route"] = "stop"
            state = self._finish(
                state,
                RequirementAgent.name,
                "completed",
                profile.impossible_reason,
                tool_calls=["deepseek:requirement", "deterministic_requirement_parser"],
            )
            return self._skip_remaining(state, SearchAndKnowledgeAgent.name, profile.impossible_reason)
        if questions:
            state["status"] = "needs_clarification"
            state["route"] = "stop"
            state = self._finish(
                state,
                RequirementAgent.name,
                "completed",
                "需要用户补充关键信息",
                tool_calls=["deepseek:requirement", "deterministic_requirement_parser"],
            )
            return self._skip_remaining(state, SearchAndKnowledgeAgent.name, "等待用户补充需求")
        state["route"] = "continue"
        return self._finish(
            state,
            RequirementAgent.name,
            "completed",
            f"预算 {profile.budget_min}-{profile.budget_max} 元，目标 {profile.budget} 元",
            tool_calls=["deepseek:requirement", "deterministic_requirement_parser"],
        )

    def _search_node(self, state: AgentState) -> dict[str, Any]:
        if self.search.retriever is None:
            state = self._start(
                state,
                SearchAndKnowledgeAgent.name,
                "SerpAPI is not configured; skip external knowledge search",
                38,
            )
            state["search_result"] = {
                "status": "skipped",
                "provider": "serpapi",
                "result_count": 0,
                "results": [],
                "error": "SerpAPI is not configured",
            }
            state["route"] = "continue"
            return self._finish(
                state,
                SearchAndKnowledgeAgent.name,
                "skipped",
                "SerpAPI 未配置，已跳过知识搜索并继续硬件选型",
                tool_calls=[],
            )
        state = self._start(state, SearchAndKnowledgeAgent.name, "AI 规划检索并调用 SerpAPI", 30)
        try:
            result, response = self.search.run(state["profile"])
        except Exception as exc:
            response = self._failed_response(str(exc))
            result = {}
        state = self._record_ai(state, SearchAndKnowledgeAgent.name, response)
        if response.get("events"):
            self._run(state, SearchAndKnowledgeAgent.name)["events"] = copy.deepcopy(
                response["events"]
            )
        if response.get("status") != "success":
            return self._ai_failure(state, SearchAndKnowledgeAgent.name, HardwareSelectionAgent.name, response)
        state["search_result"] = result
        if result.get("status") != "success":
            failure = self._failed_response(result.get("error") or "SerpAPI 未返回有效证据")
            return self._tool_failure(
                state,
                SearchAndKnowledgeAgent.name,
                HardwareSelectionAgent.name,
                failure["error"],
            )
        state["route"] = "continue"
        return self._finish(
            state,
            SearchAndKnowledgeAgent.name,
            "completed",
            f"AI 规划后返回 {result.get('result_count', 0)} 条证据",
            tool_calls=[
                "deepseek:knowledge_planner",
                "local_hardware_rag",
                *(
                    ["serpapi_hardware_search"]
                    if result.get("web", {}).get("status") == "success"
                    else []
                ),
            ],
        )

    def _hardware_node(self, state: AgentState) -> dict[str, Any]:
        attempt = state.get("selection_attempts", 0) + 1
        state = self._start(
            state,
            HardwareSelectionAgent.name,
            f"DeepSeek 结构化选型，第 {attempt} 次",
            48 if attempt == 1 else 58,
        )
        parts, payload, response = self.hardware.run(
            state["request"],
            state["profile"],
            state.get("search_result", {}),
            state.get("revision_feedback"),
        )
        state["selection_attempts"] = attempt
        state["parts"] = parts
        state["selection_payload"] = payload
        state["llm_meta"] = self._public_ai(response)
        state = self._record_ai(state, HardwareSelectionAgent.name, response)
        if response.get("status") != "success" or not parts:
            return self._ai_failure(
                state,
                HardwareSelectionAgent.name,
                CompatibilityAndPricingAgent.name,
                response,
            )
        self._run(state, HardwareSelectionAgent.name)["events"] = [
            {
                "phase": "execute",
                "name": "deepseek",
                "summary": f"AI generated {len(parts)} purchase items",
                "rationale": payload.get("rationale", []),
            },
            {
                "phase": "tool",
                "name": "normalize_build_schema",
                "summary": "Normalized AI output fields without selecting or replacing parts",
            },
        ]
        state["route"] = "continue"
        return self._finish(
            state,
            HardwareSelectionAgent.name,
            "completed",
            f"DeepSeek 生成 {len(parts)} 个采购项",
            tool_calls=["deepseek:hardware_selection"],
            iterations=attempt,
        )

    def _compatibility_node(self, state: AgentState) -> dict[str, Any]:
        state = self._start(
            state,
            CompatibilityAndPricingAgent.name,
            "确定性硬校验后由 DeepSeek 复核风险",
            72,
        )
        evaluation, events, responses = self.compatibility.run(
            state.get("parts", []), state["profile"]
        )
        state["evaluation"] = evaluation
        self._run(state, CompatibilityAndPricingAgent.name)["events"] = events
        for response in responses:
            state = self._record_ai(state, CompatibilityAndPricingAgent.name, response)
            if response.get("status") != "success":
                return self._ai_failure(
                    state,
                    CompatibilityAndPricingAgent.name,
                    ReportAgent.name,
                    response,
                )

        budget = evaluation["budget_check"]
        if evaluation["publishable"]:
            state["route"] = "report"
            return self._finish(
                state,
                CompatibilityAndPricingAgent.name,
                "completed",
                f"AI 复核完成，硬校验通过，总价 {budget['estimated_total']} 元",
                tool_calls=["deterministic_hard_gates", "deepseek:compatibility_review"],
                iterations=max(1, state.get("selection_attempts", 0)),
            )

        issues = [check["detail"] for check in evaluation["checks"] if not check.get("passed")]
        state["revision_feedback"] = (
            f"总价 {budget['estimated_total']} 元，要求 {budget['budget_min']}-{budget['budget_max']} 元；"
            f"问题：{'；'.join(issues) if issues else '预算不通过'}"
        )
        if state.get("selection_attempts", 0) < 2:
            state["route"] = "retry"
            return self._finish(
                state,
                CompatibilityAndPricingAgent.name,
                "failed",
                "第一版未通过，返回 AI 选型节点执行唯一一次重选",
                tool_calls=["deterministic_hard_gates", "deepseek:compatibility_review"],
                iterations=1,
            )

        state["status"] = "degraded"
        state["route"] = "stop"
        state["degraded_reason"] = "两次 DeepSeek 方案均未满足预算、兼容性与功耗硬约束，禁止发布采购清单"
        state = self._finish(
            state,
            CompatibilityAndPricingAgent.name,
            "failed",
            state["degraded_reason"],
            tool_calls=["deterministic_hard_gates", "deepseek:compatibility_review"],
            iterations=2,
        )
        return self._skip_remaining(state, ReportAgent.name, state["degraded_reason"])

    def _report_node(self, state: AgentState) -> dict[str, Any]:
        state = self._start(state, ReportAgent.name, "DeepSeek 整理已通过硬校验的报告", 92)
        result, response = self.report.run(state)
        state = self._record_ai(state, ReportAgent.name, response)
        if response.get("status") != "success":
            return self._ai_failure(state, ReportAgent.name, None, response)
        self._run(state, ReportAgent.name)["events"] = [
            {
                "phase": "report",
                "name": "deepseek",
                "summary": response["result"].get("summary", "AI report completed"),
                "rationale": response["result"].get("rationale", []),
                "risks": response["result"].get("risks", []),
            }
        ]
        result["ai_usage"] = copy.deepcopy(state["ai_usage"])
        result["provenance"]["llm"]["agent_call_count"] = len(state["ai_calls"])
        state["result"] = result
        state["status"] = "completed"
        state["route"] = "stop"
        return self._finish(
            state,
            ReportAgent.name,
            "completed",
            "第六个 AI 节点完成，最终报告已发布",
            tool_calls=["deepseek:report"],
        )

    def _record_ai(
        self, state: AgentState, name: str, response: dict[str, Any]
    ) -> AgentState:
        state = copy.deepcopy(state)
        call = {"agent_name": name, **self._public_ai(response)}
        state.setdefault("ai_calls", []).append(call)
        usage = state.setdefault(
            "ai_usage",
            {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        for key in ["input_tokens", "output_tokens", "total_tokens"]:
            usage[key] += int(response.get("usage", {}).get(key, 0) or 0)
        run = self._run(state, name)
        run.setdefault("ai_calls", []).append(call)
        run["ai_call"] = call
        return state

    def _ai_failure(
        self,
        state: AgentState,
        name: str,
        next_name: str | None,
        response: dict[str, Any],
    ) -> AgentState:
        error = response.get("error") or "DeepSeek 调用失败"
        state["status"] = "degraded"
        state["route"] = "stop"
        state["degraded_reason"] = f"{name} AI 调用失败：{error}"
        state = self._finish(
            state,
            name,
            "failed",
            state["degraded_reason"],
            tool_calls=[f"deepseek:{name}"],
            error=error,
        )
        if next_name:
            return self._skip_remaining(state, next_name, "上游必要 AI 节点失败")
        state["current_agent"] = None
        state["progress"] = 100
        self._persist(state)
        return state

    def _tool_failure(
        self,
        state: AgentState,
        name: str,
        next_name: str,
        error: str,
    ) -> AgentState:
        state["status"] = "degraded"
        state["route"] = "stop"
        state["degraded_reason"] = f"{name} 工具调用失败：{error}"
        state = self._finish(state, name, "failed", state["degraded_reason"], error=error)
        return self._skip_remaining(state, next_name, "上游检索工具失败")

    def _start(self, state: AgentState, name: str, summary: str, progress: int) -> AgentState:
        state = copy.deepcopy(state)
        run = self._run(state, name)
        run.update(
            status="running",
            input_summary=summary,
            iterations=max(1, run.get("iterations", 0) + 1),
        )
        state["started_at"] = {
            **state.get("started_at", {}),
            name: time.perf_counter(),
        }
        state["current_agent"] = name
        state["progress"] = progress
        state["status"] = "running"
        self._persist(state)
        return state

    def _finish(
        self,
        state: AgentState,
        name: str,
        status: str,
        summary: str,
        tool_calls: list[str] | None = None,
        iterations: int | None = None,
        error: str | None = None,
    ) -> AgentState:
        state = copy.deepcopy(state)
        run = self._run(state, name)
        began = state.get("started_at", {}).get(name, time.perf_counter())
        run.update(
            status=status,
            output_summary=summary,
            latency_ms=max(0, int((time.perf_counter() - began) * 1000)),
            tool_calls=tool_calls if tool_calls is not None else run.get("tool_calls", []),
            error=error,
        )
        if iterations is not None:
            run["iterations"] = iterations
        self._persist(state)
        return state

    def _skip_remaining(self, state: AgentState, start_name: str, reason: str) -> AgentState:
        state = copy.deepcopy(state)
        start = AGENT_NAMES.index(start_name)
        for name in AGENT_NAMES[start:]:
            run = self._run(state, name)
            if run["status"] == "pending":
                run.update(status="skipped", output_summary=reason)
        state["current_agent"] = None
        state["progress"] = 100
        self._persist(state)
        return state

    @staticmethod
    def _public_ai(response: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": response.get("status", "failed"),
            "provider": response.get("provider", "deepseek"),
            "model": response.get("model"),
            "latency_ms": response.get("latency_ms", 0),
            "usage": copy.deepcopy(response.get("usage", {})),
            "error": response.get("error"),
        }

    @staticmethod
    def _failed_response(error: str) -> dict[str, Any]:
        return {
            "status": "failed",
            "provider": "deepseek",
            "model": None,
            "latency_ms": 0,
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "result": {},
            "error": str(error)[:500],
        }

    @staticmethod
    def _run(state: AgentState, name: str) -> dict[str, Any]:
        return next(run for run in state["agent_runs"] if run["agent_name"] == name)

    def _persist(self, state: AgentState) -> None:
        with self.lock:
            existing = self.tasks.get(state["task_id"]) or {}
            existing.update(
                {
                    "task_id": state["task_id"],
                    "status": state.get("status", existing.get("status", "running")),
                    "progress": state.get("progress", existing.get("progress", 0)),
                    "current_agent": state.get("current_agent"),
                    "degraded_reason": state.get("degraded_reason"),
                    "follow_up_questions": state.get("follow_up_questions", []),
                    "agent_runs": copy.deepcopy(state["agent_runs"]),
                    "ai_usage": copy.deepcopy(state.get("ai_usage", {})),
                }
            )
            if state.get("result") is not None:
                existing["result"] = copy.deepcopy(state["result"])
            self.tasks.save(state["task_id"], existing)
