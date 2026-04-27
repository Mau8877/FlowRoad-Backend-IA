from typing import Any

from pydantic import BaseModel, Field


class WorkerAiAssistRequest(BaseModel):
    task_name: str = Field(min_length=1)
    template_name: str = Field(min_length=1)
    fields: list[dict[str, Any]] = Field(default_factory=list)
    current_answers: dict[str, Any] = Field(default_factory=dict)
    process_history: list[dict[str, Any]] = Field(default_factory=list)
    worker_note: str | None = None


class WorkerAiAssistResponse(BaseModel):
    message: str
    raw_response: str