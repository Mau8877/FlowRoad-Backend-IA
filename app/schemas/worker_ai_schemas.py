from enum import Enum
from typing import Any

from pydantic import (AliasChoices, BaseModel, Field, field_validator,
                      model_validator)


class WorkerFieldType(str, Enum):
    TEXT = "TEXT"
    TEXTAREA = "TEXTAREA"
    NUMBER = "NUMBER"
    SELECT = "SELECT"
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"
    DATE = "DATE"
    FILE = "FILE"
    PHOTO = "PHOTO"


class WorkerTemplateOption(BaseModel):
    label: str
    value: str


class WorkerTemplateFieldUiProps(BaseModel):
    grid_cols: int = Field(
        default=1,
        ge=1,
        le=2,
        validation_alias=AliasChoices("grid_cols", "gridCols"),
    )


class WorkerTemplateField(BaseModel):
    field_id: str = Field(
        validation_alias=AliasChoices("field_id", "fieldId"),
    )
    type: WorkerFieldType
    label: str
    required: bool = False
    options: list[WorkerTemplateOption] = Field(default_factory=list)
    ui_props: WorkerTemplateFieldUiProps | None = Field(
        default=None,
        validation_alias=AliasChoices("ui_props", "uiProps"),
    )

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().upper()

        return value

    @model_validator(mode="after")
    def validate_options_by_type(self) -> "WorkerTemplateField":
        if (
            self.type
            in {
                WorkerFieldType.SELECT,
                WorkerFieldType.MULTIPLE_CHOICE,
            }
            and not self.options
        ):
            raise ValueError("SELECT y MULTIPLE_CHOICE deben tener options.")

        return self


class WorkerTemplateContext(BaseModel):
    id: str | None = None
    name: str
    description: str | None = None
    department_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("department_id", "departmentId"),
    )
    version: int | None = None
    is_active: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("is_active", "isActive"),
    )
    fields: list[WorkerTemplateField] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_mongo_id(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        if data.get("id"):
            return data

        raw_id = data.get("_id")

        if isinstance(raw_id, dict):
            oid = raw_id.get("$oid")

            if oid:
                data["id"] = oid

        elif raw_id:
            data["id"] = str(raw_id)

        return data

    @model_validator(mode="after")
    def validate_fields(self) -> "WorkerTemplateContext":
        if not self.fields:
            raise ValueError("La plantilla debe tener al menos un campo.")

        return self


class WorkerAiRequest(BaseModel):
    worker_message: str = Field(
        min_length=1,
        validation_alias=AliasChoices("worker_message", "workerMessage"),
    )
    task_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("task_name", "taskName"),
    )
    process_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("process_name", "processName"),
    )
    worker_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("worker_name", "workerName"),
    )
    department_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("department_name", "departmentName"),
    )
    target_field_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("target_field_id", "targetFieldId"),
    )
    template: WorkerTemplateContext
    current_values: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("current_values", "currentValues"),
    )
    extra_context: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("extra_context", "extraContext"),
    )

    @model_validator(mode="after")
    def validate_target_field_id(self) -> "WorkerAiRequest":
        if not self.target_field_id:
            return self

        field_ids = {field.field_id for field in self.template.fields}

        if self.target_field_id not in field_ids:
            raise ValueError(
                "target_field_id no existe dentro de template.fields."
            )

        return self


class WorkerFieldSuggestion(BaseModel):
    field_id: str
    label: str
    type: WorkerFieldType
    suggested_value: Any = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warning: str | None = None

    @field_validator("field_id", "label")
    @classmethod
    def validate_not_empty(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("El valor no puede estar vacío.")

        return cleaned


class WorkerAiResponse(BaseModel):
    message: str
    field_suggestions: list[WorkerFieldSuggestion] = Field(
        default_factory=list,
    )
    warnings: list[str] = Field(default_factory=list)
