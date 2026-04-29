from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def to_camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(word.capitalize() for word in parts[1:])


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )


class DashboardStatusCount(ApiModel):
    status: str
    label: str
    count: int = 0


class DepartmentPendingTasks(ApiModel):
    department_id: str | None = None
    department_name: str = "Sin departamento"
    pending_tasks: int = 0


class PopularProcess(ApiModel):
    diagram_id: str | None = None
    diagram_name: str = "Proceso sin nombre"
    total_instances: int = 0


class DashboardAiAnalysisRequest(ApiModel):
    total_processes: int = 0
    completed_processes: int = 0
    running_processes: int = 0
    pending_assignment_processes: int = 0
    cancelled_processes: int = 0
    completion_rate: float = 0.0
    average_completion_time_minutes: int = 0
    average_completion_time_label: str = "0min"
    processes_by_status: list[DashboardStatusCount] = Field(default_factory=list)
    pending_tasks_by_department: list[DepartmentPendingTasks] = Field(
        default_factory=list
    )
    most_used_processes: list[PopularProcess] = Field(default_factory=list)
    generated_at: datetime | str | None = None
    extra_context: dict[str, Any] | None = None


class DashboardAiAnalysisResponse(ApiModel):
    summary: str
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    severity_label: str
    main_bottleneck: str
    evidence: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    generated_by: Literal["AI", "LOCAL_FALLBACK"] = "LOCAL_FALLBACK"
    generated_at: datetime = Field(default_factory=utc_now)
    provider_error: str | None = None