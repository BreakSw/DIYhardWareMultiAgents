import asyncio
import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.deps import get_recommendation_service
from app.core.response import success
from app.schemas.recommendations import RecommendationRequest
from app.services.recommender import RecommendationService


router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_recommendation(
    request: RecommendationRequest,
    background_tasks: BackgroundTasks,
    service: RecommendationService = Depends(get_recommendation_service),
) -> dict:
    created = service.create_task(request)
    background_tasks.add_task(service.run_task, created["task_id"])
    return success(created)


@router.get("/{task_id}")
def get_recommendation(
    task_id: str,
    service: RecommendationService = Depends(get_recommendation_service),
) -> dict:
    task_status = service.get_status(task_id)
    if task_status is None:
        raise HTTPException(status_code=404, detail="recommendation task not found")
    result = service.get_result(task_id)
    if result is None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "recommendation is not ready",
                "status": task_status["status"],
                "follow_up_questions": task_status["follow_up_questions"],
            },
        )
    return success(result)


@router.get("/{task_id}/status")
def get_status(
    task_id: str,
    service: RecommendationService = Depends(get_recommendation_service),
) -> dict:
    result = service.get_status(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="recommendation task not found")
    return success(result)


@router.get("/{task_id}/trace")
def get_trace(
    task_id: str,
    service: RecommendationService = Depends(get_recommendation_service),
) -> dict:
    result = service.get_trace(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="recommendation task not found")
    return success(result)


@router.get("/{task_id}/stream")
async def stream_recommendation(
    task_id: str,
    service: RecommendationService = Depends(get_recommendation_service),
) -> StreamingResponse:
    if service.get_status(task_id) is None:
        raise HTTPException(status_code=404, detail="recommendation task not found")

    async def events():
        previous = ""
        terminal = {"completed", "needs_clarification", "degraded", "failed"}
        while True:
            task_status = service.get_status(task_id)
            if task_status is None:
                yield _sse("error", {"message": "recommendation task not found"})
                return
            serialized = json.dumps(task_status, ensure_ascii=False, default=str)
            if serialized != previous:
                yield _sse("status", task_status)
                previous = serialized
            if task_status["status"] in terminal:
                result = service.get_result(task_id)
                if result is not None:
                    for chunk in _result_chunks(result):
                        yield _sse("answer", chunk)
                        await asyncio.sleep(0.025)
                    yield _sse("result", result)
                yield _sse("done", {"status": task_status["status"]})
                return
            await asyncio.sleep(0.35)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _result_chunks(result: dict) -> list[dict]:
    chunks = [
        {
            "kind": "summary",
            "content": (
                f"方案已完成：总价约 ¥{result.get('total_price', 0):,}，"
                f"适配评分 {result.get('score', 0)}/100。"
            ),
        }
    ]
    chunks.extend({"kind": "part", "content": part} for part in result.get("parts", []))
    chunks.extend(
        {"kind": "rationale", "content": line} for line in result.get("rationale", [])
    )
    chunks.append({"kind": "complete", "content": "完整方案与审计信息已加载。"})
    return chunks
