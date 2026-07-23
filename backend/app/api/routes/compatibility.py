from fastapi import APIRouter, Depends

from app.api.deps import get_recommendation_service
from app.core.response import success
from app.schemas.recommendations import CompatibilityRequest
from app.services.recommender import RecommendationService


router = APIRouter(prefix="/compatibility", tags=["compatibility"])


@router.post("/check")
def check_compatibility(request: CompatibilityRequest, service: RecommendationService = Depends(get_recommendation_service)) -> dict:
    return success({"checks": service.compatibility.check(request.parts)})
