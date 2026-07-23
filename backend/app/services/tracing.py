from datetime import datetime, timezone

from app.repositories.catalog import InMemoryTaskRepository


class TraceService:
    def __init__(self, repository: InMemoryTaskRepository) -> None:
        self.repository = repository

    def record(self, task_id: str, stage: str, status: str, detail: str) -> None:
        self.repository.add_trace(task_id, {"stage": stage, "status": status, "detail": detail, "created_at": datetime.now(timezone.utc).isoformat()})
