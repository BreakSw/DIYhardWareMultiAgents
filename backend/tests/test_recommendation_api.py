from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import get_recommendation_service
from app.main import app
from app.repositories.catalog import InMemoryCatalogRepository, InMemoryTaskRepository
from app.schemas.recommendations import RecommendationRequest
from app.services.recommender import RecommendationService
from tests.test_conversation_behavior import (
    ConversationWorkflowBrain,
    NeverCalledRetriever,
    NeverCalledSearch,
)
from tests.test_langgraph_behaviors import BudgetAwareFakeLlm, FakeRagRetriever, FakeSearchClient


def make_service() -> RecommendationService:
    return RecommendationService(
        InMemoryCatalogRepository(),
        InMemoryTaskRepository(),
        search_client=FakeSearchClient(),
        llm_client=BudgetAwareFakeLlm(),
        rag_retriever=FakeRagRetriever(),
    )


def test_async_task_api_status_result_and_trace() -> None:
    service = make_service()
    app.dependency_overrides[get_recommendation_service] = lambda: service
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/recommendations",
                json={"text": "预算 6000 到 8000 元，主要玩 2K 3A 游戏，只要主机"},
            )
            assert created.status_code == 202
            task_id = created.json()["data"]["task_id"]

            status = client.get(f"/api/v1/recommendations/{task_id}/status")
            assert status.status_code == 200
            assert status.json()["data"]["status"] == "completed"
            assert len(status.json()["data"]["agent_runs"]) == 8

            result = client.get(f"/api/v1/recommendations/{task_id}")
            assert result.status_code == 200
            assert result.json()["data"]["budget_check"]["passed"] is True

            trace = client.get(f"/api/v1/recommendations/{task_id}/trace")
            assert trace.status_code == 200
            assert len(trace.json()["data"]["events"]) == 8

            missing = client.get("/api/v1/recommendations/task_missing/status")
            assert missing.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_stream_and_hardware_catalog_endpoints() -> None:
    service = make_service()
    created = service.create_task(
        RecommendationRequest(text="预算 6000 到 8000 元，主要玩 2K 游戏，只要主机")
    )
    service.run_task(created["task_id"])
    app.dependency_overrides[get_recommendation_service] = lambda: service
    try:
        with TestClient(app) as client:
            streamed = client.get(f"/api/v1/recommendations/{created['task_id']}/stream")
            assert streamed.status_code == 200
            assert "event: status" in streamed.text
            assert "event: result" in streamed.text
            assert "event: done" in streamed.text

            catalog = client.get("/api/v1/hardware/catalog?category=gpu&limit=3")
            assert catalog.status_code == 200
            payload = catalog.json()["data"]
            assert payload["items"]
            assert all(item["category"] == "gpu" for item in payload["items"])
            assert "categories" in payload
    finally:
        app.dependency_overrides.clear()


def _conversation_service(mode: str) -> RecommendationService:
    return RecommendationService(
        InMemoryCatalogRepository(),
        InMemoryTaskRepository(),
        search_client=NeverCalledSearch(),
        llm_client=ConversationWorkflowBrain(mode),
        rag_retriever=NeverCalledRetriever(),
    )


def test_casual_status_and_stream_include_assistant_message_without_result() -> None:
    service = _conversation_service("casual")
    created = service.create_task(RecommendationRequest(text="你好，辛苦啦"))
    service.run_task(created["task_id"])
    app.dependency_overrides[get_recommendation_service] = lambda: service
    try:
        with TestClient(app) as client:
            status = client.get(
                f"/api/v1/recommendations/{created['task_id']}/status"
            )
            assert status.status_code == 200
            payload = status.json()["data"]
            assert payload["response_kind"] == "casual"
            assert payload["assistant_message"]

            streamed = client.get(
                f"/api/v1/recommendations/{created['task_id']}/stream"
            )
            assert streamed.status_code == 200
            assert "event: answer" in streamed.text
            assert '"kind": "message"' in streamed.text
            assert "event: done" in streamed.text
            assert "event: result" not in streamed.text
    finally:
        app.dependency_overrides.clear()


def test_clarification_streams_partial_answer_and_questions_without_result() -> None:
    service = _conversation_service("clarification")
    created = service.create_task(
        RecommendationRequest(text="预算一万元，想配电脑")
    )
    service.run_task(created["task_id"])
    app.dependency_overrides[get_recommendation_service] = lambda: service
    try:
        with TestClient(app) as client:
            streamed = client.get(
                f"/api/v1/recommendations/{created['task_id']}/stream"
            )
            assert streamed.status_code == 200
            assert "event: answer" in streamed.text
            assert "一万元预算" in streamed.text
            assert "主要用于" in streamed.text
            assert "event: result" not in streamed.text
    finally:
        app.dependency_overrides.clear()
