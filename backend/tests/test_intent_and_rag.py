from __future__ import annotations

import json
from pathlib import Path

from app.agents.intent_classification import IntentClassificationAgent
from app.agents.search_knowledge import SearchAndKnowledgeAgent
from app.schemas.recommendations import RequirementProfile
from app.services.rag_retriever import CatalogRagRetriever
from app.repositories.catalog import InMemoryCatalogRepository, InMemoryTaskRepository
from app.schemas.recommendations import RecommendationRequest
from app.services.recommender import RecommendationService


def _success(result: dict) -> dict:
    return {
        "status": "success",
        "provider": "deepseek",
        "model": "fake",
        "latency_ms": 1,
        "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
        "result": result,
        "error": None,
    }


class IntentBrain:
    def __init__(self, in_scope: bool) -> None:
        self.in_scope = in_scope
        self.calls: list[tuple[str, dict]] = []

    def invoke_agent(self, agent_name, payload, response_model):
        self.calls.append((agent_name, payload))
        return _success(
            {
                "is_pc_build_request": self.in_scope,
                "request_type": "pc_build" if self.in_scope else "off_topic",
                "confidence": 0.98,
                "reason": "用户要求电脑配置" if self.in_scope else "与电脑装机无关",
            }
        )


def test_intent_agent_delegates_scope_decision_to_llm() -> None:
    brain = IntentBrain(in_scope=False)

    response = IntentClassificationAgent(brain).run("请给我写一首诗")

    assert response["result"]["is_pc_build_request"] is False
    assert brain.calls[0][0] == "IntentClassificationAgent"
    assert "请给我写一首诗" in json.dumps(brain.calls[0][1], ensure_ascii=False)


class FakeEmbeddingClient:
    model_name = "fake-embedding"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    @staticmethod
    def _vector(text: str) -> list[float]:
        lowered = text.lower()
        return [1.0, 0.0] if "gpu" in lowered or "显卡" in text else [0.0, 1.0]


def _write_catalog(path: Path) -> None:
    path.mkdir(parents=True)
    records = [
        {
            "category": "cpu",
            "brand": "AMD",
            "model": "CPU Example",
            "specs": {"socket": "AM5"},
            "price": {"reference_cny": "1999"},
            "sources": ["https://example.com/cpu"],
            "fetched_at": "2026-07-20T00:00:00+00:00",
            "quality_level": "verified",
        },
        {
            "category": "gpu",
            "brand": "NVIDIA",
            "model": "GPU Example",
            "specs": {"memory_gb": 16},
            "price": {"reference_cny": "6999"},
            "sources": ["https://example.com/gpu"],
            "fetched_at": "2026-07-21T00:00:00+00:00",
            "quality_level": "verified",
        },
    ]
    (path / "verified.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
        encoding="utf-8",
    )


def test_catalog_rag_uses_embeddings_and_returns_traceable_evidence(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    _write_catalog(catalog)
    retriever = CatalogRagRetriever(
        catalog,
        embedding_client=FakeEmbeddingClient(),
        cache_directory=tmp_path / "index",
    )

    result = retriever.retrieve("高性能 GPU 显卡", top_k=1)

    assert result["status"] == "success"
    assert result["retrieval_mode"] == "vector"
    assert result["results"][0]["category"] == "gpu"
    assert result["results"][0]["link"] == "https://example.com/gpu"
    assert result["results"][0]["retrieval_score"] > 0


class RagOnlyBrain:
    def invoke_agent(self, agent_name, payload, response_model):
        return _success(
            {
                "summary": "优先检索本地知识库",
                "observations": ["需要显卡和处理器价格证据"],
                "query": "8000 元 2K 游戏主机配件",
                "use_web_search": False,
                "web_search_reason": "本地知识足够",
            }
        )


class FakeRagRetriever:
    def __init__(self) -> None:
        self.query = ""

    def retrieve(self, query: str, *, top_k: int | None = None) -> dict:
        self.query = query
        return {
            "status": "success",
            "provider": "local-rag",
            "retrieval_mode": "vector",
            "result_count": 1,
            "catalog_count": 80,
            "results": [
                {
                    "title": "RAG GPU",
                    "link": "https://example.com/rag-gpu",
                    "source": "local-rag:verified",
                    "price": "6999",
                    "category": "gpu",
                    "specs": {"memory_gb": 16},
                    "retrieval_score": 0.91,
                }
            ],
            "error": None,
        }


class DisabledWebSearch:
    is_configured = False

    def search_hardware(self, profile, query=None):
        raise AssertionError("SerpAPI must not run when the AI does not request it")


def test_search_agent_uses_local_rag_without_serpapi() -> None:
    rag = FakeRagRetriever()
    profile = RequirementProfile(budget=8000, budget_min=7000, budget_max=8000)

    result, response = SearchAndKnowledgeAgent(
        DisabledWebSearch(), RagOnlyBrain(), rag
    ).run(profile)

    assert rag.query == "8000 元 2K 游戏主机配件"
    assert result["results"][0]["source"] == "local-rag:verified"
    assert result["rag"]["retrieval_mode"] == "vector"
    assert result["web"]["status"] == "skipped"
    assert any(event["name"] == "local_rag_retrieval" for event in response["events"])


class OffTopicWorkflowBrain:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def invoke_agent(self, agent_name, payload, response_model):
        self.calls.append(agent_name)
        if agent_name == "SupervisorAgent":
            return _success({"summary": "start", "observations": []})
        if agent_name == "IntentClassificationAgent":
            return _success(
                {
                    "is_pc_build_request": False,
                    "request_type": "off_topic",
                    "confidence": 0.99,
                    "reason": "与装机无关",
                    "assistant_reply": "这个问题不在我的装机专长内，我们可以聊聊电脑硬件选型。",
                }
            )
        raise AssertionError(f"unexpected downstream AI call: {agent_name}")


def test_off_topic_request_stops_after_llm_intent_decision() -> None:
    brain = OffTopicWorkflowBrain()
    service = RecommendationService(
        InMemoryCatalogRepository(),
        InMemoryTaskRepository(),
        search_client=DisabledWebSearch(),
        llm_client=brain,
        rag_retriever=FakeRagRetriever(),
    )
    created = service.create_task(RecommendationRequest(text="请给我写一首诗"))

    service.run_task(created["task_id"])
    task = service.tasks.get(created["task_id"])

    assert task["status"] == "completed"
    assert task["response_kind"] == "off_topic"
    assert "硬件选型" in task["assistant_message"]
    assert brain.calls == ["SupervisorAgent", "IntentClassificationAgent"]
    assert task["follow_up_questions"] == []
    assert [run["status"] for run in task["agent_runs"]] == [
        "completed",
        "completed",
        "skipped",
        "skipped",
        "skipped",
        "skipped",
        "skipped",
        "skipped",
    ]
