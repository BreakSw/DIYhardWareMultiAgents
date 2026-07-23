from fastapi import APIRouter, Depends

from app.api.deps import get_recommendation_service
from app.core.response import success
from app.schemas.recommendations import RequirementRequest
from app.services.recommender import RecommendationService


router = APIRouter(prefix="/requirements", tags=["requirements"])


@router.post("/parse")
def parse_requirement(request: RequirementRequest, service: RecommendationService = Depends(get_recommendation_service)) -> dict:
    return success(service.parse(request.text).model_dump())
