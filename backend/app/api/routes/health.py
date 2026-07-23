from fastapi import APIRouter

from app.core.config import settings
from app.core.response import success


router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return success(
        {
            "status": "ok",
            "environment": settings.app_env,
            "database": "mysql-configured",
            "rag": "enabled" if settings.rag_enabled else "disabled",
            "rag_provider": (
                "voyage-local-index" if settings.embedding_api_key else "lexical-local-index"
            ),
            "redis": "disabled",
        }
    )
