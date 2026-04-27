from fastapi import APIRouter

from app.schemas.diagram_ai_schemas import (
    DiagramAiRawResponse,
    DiagramAiRequest,
    DiagramAiResponse,
)
from app.services.diagram_ai_service import DiagramAiService

router = APIRouter(prefix="/ai/diagram", tags=["Diagram AI"])


@router.post("/message", response_model=DiagramAiResponse)
async def generate_or_edit_diagram(
    request: DiagramAiRequest,
) -> DiagramAiResponse:
    service = DiagramAiService()
    return await service.generate_or_edit_diagram(request)


@router.post("/message/raw", response_model=DiagramAiRawResponse)
async def generate_or_edit_diagram_raw(
    request: DiagramAiRequest,
) -> DiagramAiRawResponse:
    service = DiagramAiService()
    return await service.generate_or_edit_diagram_raw(request)