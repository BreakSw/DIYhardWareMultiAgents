from functools import lru_cache

from app.repositories.catalog import InMemoryCatalogRepository, InMemoryTaskRepository
from app.services.recommender import RecommendationService


@lru_cache
def get_recommendation_service() -> RecommendationService:
    return RecommendationService(InMemoryCatalogRepository(), InMemoryTaskRepository())
