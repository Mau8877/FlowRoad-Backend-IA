from fastapi import APIRouter

from app.schemas.worker_ai_schemas import WorkerAiRequest, WorkerAiResponse
from app.services.worker_ai_service import WorkerAiService

router = APIRouter(
    prefix="/ai/worker",
    tags=["Worker AI"],
)

worker_ai_service = WorkerAiService()


@router.post(
    "/template-assist",
    response_model=WorkerAiResponse,
)
async def assist_template(
    request: WorkerAiRequest,
) -> WorkerAiResponse:
    return await worker_ai_service.assist_template(request)


@router.post(
    "/fill-template",
    response_model=WorkerAiResponse,
)
async def fill_template(
    request: WorkerAiRequest,
) -> WorkerAiResponse:
    return await worker_ai_service.assist_template(request)
