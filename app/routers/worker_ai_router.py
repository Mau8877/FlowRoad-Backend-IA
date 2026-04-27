from fastapi import APIRouter

from app.schemas.worker_ai_schemas import (
    WorkerAiAssistRequest,
    WorkerAiAssistResponse,
)
from app.services.worker_ai_service import WorkerAiService

router = APIRouter(prefix="/ai/worker", tags=["Worker AI"])


@router.post("/assist", response_model=WorkerAiAssistResponse)
async def assist_worker(
    request: WorkerAiAssistRequest,
) -> WorkerAiAssistResponse:
    service = WorkerAiService()
    return await service.assist_worker(request)