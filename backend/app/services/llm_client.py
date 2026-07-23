from __future__ import annotations

import json
import time
from typing import Any, Literal

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.core.config import settings
from app.schemas.recommendations import RequirementProfile


class BuildPart(BaseModel):
    id: str
    category: str
    name: str
    price: int = Field(ge=0)
    specs: dict[str, Any] = Field(default_factory=dict)


class BuildAlternative(BaseModel):
    title: str
    detail: str
    delta: int


class BuildPlan(BaseModel):
    profile: dict[str, Any] = Field(default_factory=dict)
    parts: list[BuildPart]
    rationale: list[str] = Field(default_factory=list)
    alternatives: list[BuildAlternative] = Field(default_factory=list)


class AgentInsight(BaseModel):
    summary: str
    observations: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    query: str = ""
    rationale: list[str] = Field(default_factory=list)
    alternatives: list[BuildAlternative] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class ToolPlan(BaseModel):
    summary: str
    tool_calls: list[str] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)


class ReportNarrative(BaseModel):
    summary: str
    rationale: list[str] = Field(min_length=1)
    alternatives: list[BuildAlternative] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class RequirementAnalysis(BaseModel):
    summary: str
    usage: str
    usage_explicit: bool
    resolution: str = "2K"
    case_size: str = "ATX"
    include_peripherals: bool = False
    peripherals_explicit: bool = False
    allow_under_budget: bool = False
    owned_parts: dict[str, str] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    missing_fields: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    impossible_reason: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    partial_answer: str = ""


class IntentClassification(BaseModel):
    is_pc_build_request: bool
    request_type: Literal[
        "pc_build", "pc_upgrade", "hardware_consultation", "casual", "off_topic"
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    assistant_reply: str = ""


class KnowledgePlan(BaseModel):
    summary: str
    observations: list[str] = Field(default_factory=list)
    query: str
    use_web_search: bool = False
    web_search_reason: str = ""


class DeepSeekClient:
    """Shared LangChain brain invoked independently by every graph agent."""

    def __init__(self, chat_model: Any | None = None) -> None:
        self._chat_model = chat_model

    def invoke_agent(
        self,
        agent_name: str,
        payload: dict[str, Any],
        response_model: type[BaseModel],
    ) -> dict[str, Any]:
        if not settings.model_api_key and self._chat_model is None:
            return self._unavailable("DeepSeek API key 未配置")

        started = time.perf_counter()
        try:
            model = self._chat_model or self._build_model()
            schema = json.dumps(response_model.model_json_schema(), ensure_ascii=False)
            message = model.invoke(
                [
                    SystemMessage(
                        content=(
                            f"你是七节点多智能体装机系统中的 {agent_name}。只完成该角色职责。"
                            "必须只输出一个合法 JSON 对象，不要使用 Markdown 代码块。"
                            f"输出 JSON Schema：{schema}"
                        )
                    ),
                    HumanMessage(content=json.dumps(payload, ensure_ascii=False, default=str)),
                ]
            )
            parsed = response_model.model_validate(self._parse_json(message.content))
            return {
                "status": "success",
                "provider": "deepseek",
                "model": settings.model_name,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "usage": self._usage(message),
                "result": parsed.model_dump(),
                "error": None,
            }
        except Exception as exc:
            return self._unavailable(str(exc), int((time.perf_counter() - started) * 1000))

    def generate_build(
        self,
        user_text: str,
        profile: RequirementProfile,
        search: dict[str, Any],
        revision_feedback: str | None = None,
    ) -> dict[str, Any]:
        prompt = self._build_prompt(user_text, profile, search.get("results", []), revision_feedback)
        response = self.invoke_agent("HardwareSelectionAgent", {"prompt": prompt}, BuildPlan)
        if response.get("status") == "success" and len(response["result"].get("parts", [])) < 7:
            return self._unavailable(
                "模型没有返回完整的部件列表",
                response.get("latency_ms", 0),
                response.get("usage"),
            )
        return response

    @staticmethod
    def _build_model() -> ChatOpenAI:
        client = httpx.Client(
            trust_env=False,
            timeout=float(settings.model_timeout),
        )
        return ChatOpenAI(
            model=settings.model_name,
            api_key=settings.model_api_key,
            base_url=settings.model_base_url.rstrip("/"),
            temperature=0.2,
            max_tokens=3000,
            timeout=float(settings.model_timeout),
            max_retries=1,
            http_client=client,
        )

    @staticmethod
    def _parse_json(content: Any) -> dict[str, Any]:
        text = content if isinstance(content, str) else str(content)
        fence = chr(96) * 3
        text = text.replace(fence + "json", "").replace(fence, "").strip()
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < start:
            raise ValueError("DeepSeek 未返回 JSON 对象")
        value = json.loads(text[start : end + 1])
        if not isinstance(value, dict):
            raise ValueError("DeepSeek JSON 顶层必须是对象")
        return value

    @staticmethod
    def _usage(message: Any) -> dict[str, int]:
        raw = getattr(message, "usage_metadata", None) or {}
        metadata = getattr(message, "response_metadata", None) or {}
        token_usage = metadata.get("token_usage", {})
        input_tokens = int(raw.get("input_tokens") or token_usage.get("prompt_tokens") or 0)
        output_tokens = int(raw.get("output_tokens") or token_usage.get("completion_tokens") or 0)
        total_tokens = int(
            raw.get("total_tokens")
            or token_usage.get("total_tokens")
            or input_tokens + output_tokens
        )
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }

    @staticmethod
    def _build_prompt(
        user_text: str,
        profile: RequirementProfile,
        evidence: list[dict[str, Any]],
        revision_feedback: str | None,
    ) -> str:
        evidence_text = json.dumps(evidence, ensure_ascii=False)[:9000]
        required_categories = ["cpu", "motherboard", "memory", "storage", "psu", "cooler", "case"]
        if "gpu" not in profile.owned_parts:
            required_categories.insert(1, "gpu")
        return f"""
用户原始需求：{user_text}
不可覆盖的确定性需求：{profile.model_dump_json()}
必须采购的部件分类：{required_categories}
已有部件：{json.dumps(profile.owned_parts, ensure_ascii=False)}
SerpAPI 搜索证据：{evidence_text}
上一次硬校验反馈：{revision_feedback or "无，这是第一次选型"}

生成一套完整、可购买的配置。采购总价必须不低于 budget_min；budget_max 不为 null 时还必须满足 total <= budget_max；
只有 allow_under_budget=true 时才允许低于 budget_min，但仍应解释节省原因。
已有部件不得出现在采购清单中，也不得计入总价。若包含外设，应在 parts 中使用
monitor、keyboard、mouse 等分类。所有价格为人民币整数。
specs 至少包含：CPU socket/tdp；GPU length_mm/tdp；主板 socket/memory_type/form_factor；
内存 memory_type/capacity_gb；电源 watt；散热 height_mm/tdp；
机箱 max_gpu_length_mm/max_cooler_height_mm/form_factor。
只输出符合 BuildPlan 模式的 JSON。
""".strip()

    @staticmethod
    def _unavailable(
        error: str,
        latency_ms: int = 0,
        usage: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "failed",
            "provider": "deepseek",
            "model": settings.model_name,
            "latency_ms": latency_ms,
            "usage": usage or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "result": {},
            "error": error[:500],
        }
