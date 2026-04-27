from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers.diagram_ai_router import router as diagram_ai_router
from app.routers.worker_ai_router import router as worker_ai_router

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Microservicio de IA para FlowRoad.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(diagram_ai_router)
app.include_router(worker_ai_router)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "FlowRoad AI Service running",
        "environment": settings.app_env,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
    }