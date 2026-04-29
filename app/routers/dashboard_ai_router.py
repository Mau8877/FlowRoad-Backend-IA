from fastapi import APIRouter

from app.schemas.dashboard_ai_schemas import (
    DashboardAiAnalysisRequest,
    DashboardAiAnalysisResponse,
)
from app.services.dashboard_ai_service import DashboardAiService

router = APIRouter(
    prefix="/ai/dashboard",
    tags=["Dashboard AI"],
)

dashboard_ai_service = DashboardAiService()


@router.post(
    "/bottleneck-analysis",
    response_model=DashboardAiAnalysisResponse,
)
async def analyze_dashboard_bottleneck(
    request: DashboardAiAnalysisRequest,
) -> DashboardAiAnalysisResponse:
    return await dashboard_ai_service.analyze_bottleneck(request)