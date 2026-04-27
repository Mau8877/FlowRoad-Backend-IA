from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class DiagramAiMode(str, Enum):
    CREATE = "CREATE"
    EDIT = "EDIT"


class CompactNodeType(str, Enum):
    INITIAL = "INITIAL"
    FINAL = "FINAL"
    ACTION = "ACTION"
    DECISION = "DECISION"


class FieldType(str, Enum):
    TEXT = "TEXT"
    TEXTAREA = "TEXTAREA"
    NUMBER = "NUMBER"
    SELECT = "SELECT"
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"
    DATE = "DATE"
    FILE = "FILE"
    PHOTO = "PHOTO"


class TemplateStrategy(str, Enum):
    USE_EXISTING_TEMPLATE = "USE_EXISTING_TEMPLATE"
    CREATE_NEW_TEMPLATE = "CREATE_NEW_TEMPLATE"


class DepartmentContext(BaseModel):
    id: str = Field(description="ID real del departamento.")
    name: str = Field(description="Nombre visible del departamento.")


class TemplateOption(BaseModel):
    label: str
    value: str


class TemplateFieldUiProps(BaseModel):
    grid_cols: int = Field(default=1, ge=1, le=2)


class ExistingTemplateField(BaseModel):
    field_id: str | None = None
    type: FieldType
    label: str
    required: bool = False
    options: list[TemplateOption] = Field(default_factory=list)
    ui_props: TemplateFieldUiProps | None = None


class ExistingTemplateContext(BaseModel):
    id: str
    name: str
    description: str | None = None
    department_id: str | None = None
    department_name: str | None = None
    fields: list[ExistingTemplateField] = Field(default_factory=list)


class DiagramAiRequest(BaseModel):
    mode: DiagramAiMode
    user_message: str = Field(min_length=3)
    current_diagram: dict[str, Any] | None = None
    available_departments: list[DepartmentContext] = Field(default_factory=list)
    existing_templates: list[ExistingTemplateContext] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_edit_mode_has_diagram(self) -> "DiagramAiRequest":
        if self.mode == DiagramAiMode.EDIT and not self.current_diagram:
            raise ValueError(
                "current_diagram es obligatorio cuando mode es EDIT."
            )

        return self


class CompactNode(BaseModel):
    id: str
    type: CompactNodeType
    name: str
    department_id: str


class CompactLink(BaseModel):
    id: str
    source_id: str
    target_id: str
    label: str | None = None


class CompactDiagram(BaseModel):
    name: str
    description: str
    nodes: list[CompactNode] = Field(default_factory=list)
    links: list[CompactLink] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_compact_diagram(self) -> "CompactDiagram":
        node_ids = {node.id for node in self.nodes}

        initial_nodes = [
            node for node in self.nodes if node.type == CompactNodeType.INITIAL
        ]
        final_nodes = [
            node for node in self.nodes if node.type == CompactNodeType.FINAL
        ]

        if len(initial_nodes) != 1:
            raise ValueError("El diagrama debe tener exactamente un INITIAL.")

        if not final_nodes:
            raise ValueError("El diagrama debe tener al menos un FINAL.")

        for link in self.links:
            if link.source_id not in node_ids:
                raise ValueError(
                    f"El link {link.id} tiene source_id inválido."
                )

            if link.target_id not in node_ids:
                raise ValueError(
                    f"El link {link.id} tiene target_id inválido."
                )

        decision_ids = {
            node.id
            for node in self.nodes
            if node.type == CompactNodeType.DECISION
        }

        for link in self.links:
            if link.source_id in decision_ids and not link.label:
                raise ValueError(
                    f"El link {link.id} sale de DECISION y necesita label."
                )

        return self


class SuggestedTemplateField(BaseModel):
    type: FieldType
    label: str
    required: bool = False
    options: list[TemplateOption] = Field(default_factory=list)
    ui_props: TemplateFieldUiProps = Field(default_factory=TemplateFieldUiProps)

    @model_validator(mode="after")
    def validate_options_by_type(self) -> "SuggestedTemplateField":
        if self.type in {FieldType.SELECT, FieldType.MULTIPLE_CHOICE}:
            if not self.options:
                raise ValueError(
                    "SELECT y MULTIPLE_CHOICE deben tener opciones."
                )
        else:
            if self.options:
                raise ValueError(
                    f"El campo {self.type} debe tener options vacío."
                )

        return self


class SuggestedTemplate(BaseModel):
    name: str
    description: str = ""
    department_id: str
    department_name: str | None = None
    fields: list[SuggestedTemplateField] = Field(default_factory=list)


class TemplateSuggestion(BaseModel):
    node_id: str
    node_name: str
    strategy: TemplateStrategy

    existing_template_id: str | None = None
    existing_template_name: str | None = None

    template: SuggestedTemplate | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_strategy_payload(self) -> "TemplateSuggestion":
        if self.strategy == TemplateStrategy.USE_EXISTING_TEMPLATE:
            if not self.existing_template_id:
                raise ValueError(
                    "existing_template_id es obligatorio al reutilizar."
                )

            if not self.existing_template_name:
                raise ValueError(
                    "existing_template_name es obligatorio al reutilizar."
                )

            if self.template is not None:
                raise ValueError(
                    "template debe ser null al reutilizar plantilla."
                )

        if self.strategy == TemplateStrategy.CREATE_NEW_TEMPLATE:
            if self.template is None:
                raise ValueError(
                    "template es obligatorio al crear plantilla nueva."
                )

        return self


class DiagramAiCompactResponse(BaseModel):
    message: str
    mode: DiagramAiMode
    diagram: CompactDiagram
    template_suggestions: list[TemplateSuggestion] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    changes_summary: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_action_template_suggestions(
        self,
    ) -> "DiagramAiCompactResponse":
        action_ids = {
            node.id
            for node in self.diagram.nodes
            if node.type == CompactNodeType.ACTION
        }
        suggested_ids = {
            suggestion.node_id for suggestion in self.template_suggestions
        }

        missing = action_ids - suggested_ids
        if missing:
            raise ValueError(
                "Todos los ACTION deben tener template_suggestions. "
                f"Faltan: {sorted(missing)}"
            )

        return self


class FlowRoadPosition(BaseModel):
    x: float
    y: float


class FlowRoadSize(BaseModel):
    width: float
    height: float


class FlowRoadEndpoint(BaseModel):
    id: str | None = None
    port: str | None = None


class FlowRoadLane(BaseModel):
    id: str
    departmentId: str
    departmentName: str
    order: int
    x: int
    y: int
    width: int
    height: int


class FlowRoadCell(BaseModel):
    id: str
    type: str
    position: FlowRoadPosition | None = None
    size: FlowRoadSize | None = None
    source: FlowRoadEndpoint | None = None
    target: FlowRoadEndpoint | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)
    customData: dict[str, Any] = Field(default_factory=dict)
    labels: list[dict[str, Any]] | None = None
    vertices: list[dict[str, Any]] | None = None
    router: dict[str, Any] | None = None
    connector: dict[str, Any] | None = None


class FlowRoadDiagram(BaseModel):
    name: str
    description: str
    cells: list[FlowRoadCell] = Field(default_factory=list)
    lanes: list[FlowRoadLane] = Field(default_factory=list)


class DiagramAiResponse(BaseModel):
    message: str
    mode: DiagramAiMode
    diagram: FlowRoadDiagram
    template_suggestions: list[TemplateSuggestion] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    changes_summary: list[str] = Field(default_factory=list)


class DiagramAiRawResponse(BaseModel):
    message: str
    raw_response: str


class OpenRouterMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str