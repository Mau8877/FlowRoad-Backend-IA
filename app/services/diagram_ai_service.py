import json
from typing import Any

from fastapi import HTTPException, status
from pydantic import ValidationError

from app.core.diagram_ai_prompt import DIAGRAM_AI_SYSTEM_PROMPT
from app.schemas.diagram_ai_schemas import (
    CompactNode,
    CompactNodeType,
    DiagramAiCompactResponse,
    DiagramAiRawResponse,
    DiagramAiRequest,
    DiagramAiResponse,
    FlowRoadDiagram,
    TemplateStrategy,
)
from app.services.diagram_semantic_validator import DiagramSemanticValidator
from app.services.openrouter_service import OpenRouterService


class DiagramAiService:
    MAX_REPAIR_ATTEMPTS = 2

    def __init__(self) -> None:
        self.openrouter_service = OpenRouterService()
        self.semantic_validator = DiagramSemanticValidator()

    async def generate_or_edit_diagram(
        self,
        request: DiagramAiRequest,
    ) -> DiagramAiResponse:
        compact_response, _raw_response = (
            await self._generate_valid_compact_response(request)
        )

        return self._build_flowroad_response(
            compact_response=compact_response,
            request=request,
        )

    async def generate_or_edit_diagram_raw(
        self,
        request: DiagramAiRequest,
    ) -> DiagramAiRawResponse:
        raw_response = await self._call_model(request)

        return DiagramAiRawResponse(
            message="Respuesta cruda generada correctamente.",
            raw_response=raw_response,
        )

    async def _generate_valid_compact_response(
        self,
        request: DiagramAiRequest,
    ) -> tuple[DiagramAiCompactResponse, str]:
        raw_response = await self._call_model(request)

        for attempt in range(self.MAX_REPAIR_ATTEMPTS + 1):
            compact_response = self._parse_and_validate_compact_response(
                raw_response=raw_response,
                request=request,
            )

            semantic_errors = self.semantic_validator.validate(
                diagram=compact_response.diagram,
                template_suggestions=compact_response.template_suggestions,
                existing_templates=request.existing_templates,
            )

            if not semantic_errors:
                return compact_response, raw_response

            if attempt >= self.MAX_REPAIR_ATTEMPTS:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "message": (
                            "No se pudo generar una propuesta ejecutable. "
                            "Intenta describir el flujo con un poco más de "
                            "detalle."
                        ),
                        "errors": semantic_errors,
                        "raw_response": raw_response,
                    },
                )

            raw_response = await self._call_repair_model(
                request=request,
                previous_raw_response=raw_response,
                semantic_errors=semantic_errors,
            )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo completar la validación del diagrama.",
        )

    def _parse_and_validate_compact_response(
        self,
        raw_response: str,
        request: DiagramAiRequest,
    ) -> DiagramAiCompactResponse:
        parsed_response = self._parse_json_response(raw_response)
        parsed_response = self._repair_missing_template_suggestions(
            parsed_response=parsed_response,
            request=request,
        )

        try:
            return DiagramAiCompactResponse.model_validate(
                parsed_response,
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "message": (
                        "La IA devolvió JSON compacto, pero no cumple "
                        "el formato esperado."
                    ),
                    "errors": self._serialize_validation_errors(exc),
                    "raw_response": raw_response,
                },
            ) from exc

    async def _call_model(self, request: DiagramAiRequest) -> str:
        context = self._build_context(request)

        user_prompt = f"""
Necesito que generes o modifiques una propuesta compacta de diagrama FlowRoad.

Modo de trabajo:
{request.mode.value}

Instrucción del usuario:
{request.user_message}

Contexto disponible en JSON:
{json.dumps(context, ensure_ascii=False, indent=2)}

Responde exclusivamente con JSON válido.
No uses Markdown.
No uses bloque ```json.
No escribas texto fuera del JSON.

No devuelvas el JSON visual completo.
No devuelvas attrs, router, connector, position, size, vertices ni labels visuales.
Solo devuelve nodes, links y template_suggestions en formato compacto.

La respuesta debe cumplir esta estructura exacta:

{{
  "message": "Mensaje breve para el usuario",
  "mode": "{request.mode.value}",
  "diagram": {{
    "name": "Nombre del diagrama",
    "description": "Descripción del diagrama",
    "nodes": [
      {{
        "id": "node-inicio",
        "type": "INITIAL",
        "name": "Inicio",
        "department_id": "id-real-departamento"
      }}
    ],
    "links": [
      {{
        "id": "link-1",
        "source_id": "node-inicio",
        "target_id": "node-siguiente",
        "label": null
      }}
    ]
  }},
  "template_suggestions": [],
  "warnings": [],
  "changes_summary": []
}}

Reglas críticas:
- Usa únicamente department_id reales del contexto.
- Cada ACTION debe tener template_suggestions.
- Cada DECISION debe estar precedida por un ACTION con SELECT compatible.
- Todo link que salga desde DECISION debe tener label.
- Si usas plantilla existente, strategy debe ser USE_EXISTING_TEMPLATE.
- Si propones plantilla nueva, strategy debe ser CREATE_NEW_TEMPLATE.
- Usa snake_case.
- Si el usuario menciona recepción, solicitud, registro inicial o atención inicial,
  crea un ACTION inicial para esa etapa antes de avanzar a otra área.
- Si propones un SELECT decisorio en una plantilla, crea un DECISION inmediatamente
  después de ese ACTION.
- Si no creas DECISION después de un ACTION, evita poner SELECT decisorio en su plantilla.
"""

        return await self.openrouter_service.chat_completion(
            messages=[
                {"role": "system", "content": DIAGRAM_AI_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=3000,
        )

    async def _call_repair_model(
        self,
        request: DiagramAiRequest,
        previous_raw_response: str,
        semantic_errors: list[str],
    ) -> str:
        context = self._build_context(request)
        semantic_errors_text = "\n".join(
            f"- {error}" for error in semantic_errors
        )

        repair_prompt = f"""
La respuesta anterior de la IA no es ejecutable en FlowRoad.

Instrucción original del usuario:
{request.user_message}

Contexto disponible en JSON:
{json.dumps(context, ensure_ascii=False, indent=2)}

JSON compacto anterior:
{previous_raw_response}

Errores semánticos detectados:
{semantic_errors_text}

Corrige el JSON compacto completo.
Debes conservar la intención original del usuario.

Reglas obligatorias:
- Debes responder exclusivamente JSON válido.
- No uses Markdown.
- No expliques nada fuera del JSON.
- No devuelvas attrs, router, connector, position, size, vertices ni labels visuales.
- Usa solo nodes, links y template_suggestions en formato compacto.
- No inventes departamentos fuera de available_departments.
- Todo ACTION debe tener ruta hacia FINAL.
- Todo ACTION con SELECT decisorio debe tener una DECISION inmediatamente después.
- Si no pones DECISION después de un ACTION, cambia ese SELECT por un campo no decisorio.
- Toda DECISION debe tener al menos 2 salidas.
- Todo link saliente de DECISION debe tener label.
- No dejes nodos huérfanos.
- Si un ACTION queda sin salida, conéctalo al FINAL o a un nodo que llegue al FINAL.
- Cada ACTION debe tener template_suggestions.
- Si falta template_suggestion, puedes crear CREATE_NEW_TEMPLATE.
- Usa snake_case.
"""

        return await self.openrouter_service.chat_completion(
            messages=[
                {"role": "system", "content": DIAGRAM_AI_SYSTEM_PROMPT},
                {"role": "user", "content": repair_prompt},
            ],
            temperature=0.1,
            max_tokens=3000,
        )

    def _build_context(self, request: DiagramAiRequest) -> dict[str, Any]:
        return {
            "mode": request.mode.value,
            "user_message": request.user_message,
            "current_diagram": request.current_diagram,
            "available_departments": [
                department.model_dump()
                for department in request.available_departments
            ],
            "existing_templates": [
                template.model_dump()
                for template in request.existing_templates
            ],
        }

    def _repair_missing_template_suggestions(
        self,
        parsed_response: dict[str, Any],
        request: DiagramAiRequest,
    ) -> dict[str, Any]:
        diagram = parsed_response.get("diagram", {})
        nodes = diagram.get("nodes", [])
        suggestions = parsed_response.get("template_suggestions", [])

        if not isinstance(nodes, list):
            return parsed_response

        if not isinstance(suggestions, list):
            suggestions = []

        suggested_node_ids = {
            suggestion.get("node_id")
            for suggestion in suggestions
            if isinstance(suggestion, dict)
        }

        departments_by_id = {
            department.id: department.name
            for department in request.available_departments
        }

        for node in nodes:
            if not isinstance(node, dict):
                continue

            if node.get("type") != "ACTION":
                continue

            node_id = node.get("id")
            node_name = node.get("name") or "Tarea"
            department_id = node.get("department_id")

            if not node_id or node_id in suggested_node_ids:
                continue

            suggestions.append(
                {
                    "node_id": node_id,
                    "node_name": node_name,
                    "strategy": "CREATE_NEW_TEMPLATE",
                    "existing_template_id": None,
                    "existing_template_name": None,
                    "template": {
                        "name": node_name,
                        "description": (
                            f"Plantilla sugerida para la tarea: {node_name}."
                        ),
                        "department_id": department_id,
                        "department_name": departments_by_id.get(
                            department_id,
                        ),
                        "fields": self._build_default_template_fields(
                            node_name,
                        ),
                    },
                    "reason": (
                        "La IA no propuso una plantilla para este nodo ACTION, "
                        "por eso se generó una plantilla básica automáticamente."
                    ),
                }
            )

            suggested_node_ids.add(node_id)

        parsed_response["template_suggestions"] = suggestions
        return parsed_response

    def _build_default_template_fields(
        self,
        node_name: str,
    ) -> list[dict[str, Any]]:
        normalized_name = node_name.lower()

        if "disponibilidad" in normalized_name or "disponible" in normalized_name:
            return [
                {
                    "type": "SELECT",
                    "label": "¿Está disponible?",
                    "required": True,
                    "options": [
                        {
                            "label": "Si",
                            "value": "si",
                        },
                        {
                            "label": "No",
                            "value": "no",
                        },
                    ],
                    "ui_props": {
                        "grid_cols": 1,
                    },
                },
                {
                    "type": "TEXTAREA",
                    "label": "Observaciones",
                    "required": False,
                    "options": [],
                    "ui_props": {
                        "grid_cols": 2,
                    },
                },
            ]

        if "cotiz" in normalized_name:
            return [
                {
                    "type": "NUMBER",
                    "label": "Monto de cotización",
                    "required": True,
                    "options": [],
                    "ui_props": {
                        "grid_cols": 1,
                    },
                },
                {
                    "type": "TEXTAREA",
                    "label": "Detalle de cotización",
                    "required": True,
                    "options": [],
                    "ui_props": {
                        "grid_cols": 2,
                    },
                },
            ]

        if "acept" in normalized_name or "confirm" in normalized_name:
            return [
                {
                    "type": "SELECT",
                    "label": "¿El cliente acepta?",
                    "required": True,
                    "options": [
                        {
                            "label": "Si",
                            "value": "si",
                        },
                        {
                            "label": "No",
                            "value": "no",
                        },
                    ],
                    "ui_props": {
                        "grid_cols": 1,
                    },
                },
                {
                    "type": "TEXTAREA",
                    "label": "Observaciones",
                    "required": False,
                    "options": [],
                    "ui_props": {
                        "grid_cols": 2,
                    },
                },
            ]

        if "pago" in normalized_name:
            return [
                {
                    "type": "NUMBER",
                    "label": "Monto pagado",
                    "required": True,
                    "options": [],
                    "ui_props": {
                        "grid_cols": 1,
                    },
                },
                {
                    "type": "DATE",
                    "label": "Fecha de pago",
                    "required": True,
                    "options": [],
                    "ui_props": {
                        "grid_cols": 1,
                    },
                },
                {
                    "type": "FILE",
                    "label": "Comprobante de pago",
                    "required": False,
                    "options": [],
                    "ui_props": {
                        "grid_cols": 2,
                    },
                },
            ]

        if "solicitud" in normalized_name or "recepción" in normalized_name:
            return [
                {
                    "type": "TEXT",
                    "label": "Nombre del solicitante",
                    "required": True,
                    "options": [],
                    "ui_props": {
                        "grid_cols": 1,
                    },
                },
                {
                    "type": "TEXTAREA",
                    "label": "Detalle de la solicitud",
                    "required": True,
                    "options": [],
                    "ui_props": {
                        "grid_cols": 2,
                    },
                },
            ]

        return [
            {
                "type": "TEXTAREA",
                "label": "Detalle de la tarea",
                "required": True,
                "options": [],
                "ui_props": {
                    "grid_cols": 2,
                },
            },
            {
                "type": "DATE",
                "label": "Fecha de registro",
                "required": False,
                "options": [],
                "ui_props": {
                    "grid_cols": 1,
                },
            },
        ]

    def _build_flowroad_response(
        self,
        compact_response: DiagramAiCompactResponse,
        request: DiagramAiRequest,
    ) -> DiagramAiResponse:
        departments_by_id = {
            department.id: department.name
            for department in request.available_departments
        }

        if not departments_by_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debes enviar available_departments.",
            )

        warnings = list(compact_response.warnings)
        self._normalize_invalid_departments(
            compact_response.diagram.nodes,
            departments_by_id,
            warnings,
        )

        template_by_node_id = {
            suggestion.node_id: suggestion
            for suggestion in compact_response.template_suggestions
        }

        lanes = self._build_lanes(
            nodes=compact_response.diagram.nodes,
            departments_by_id=departments_by_id,
        )

        cells: list[dict[str, Any]] = []
        cells.extend(
            self._build_node_cells(
                nodes=compact_response.diagram.nodes,
                lanes=lanes,
                template_by_node_id=template_by_node_id,
            )
        )
        cells.extend(
            self._build_link_cells(
                links=compact_response.diagram.links,
                nodes=compact_response.diagram.nodes,
            )
        )

        diagram = FlowRoadDiagram(
            name=compact_response.diagram.name,
            description=compact_response.diagram.description,
            cells=cells,
            lanes=lanes,
        )

        return DiagramAiResponse(
            message=compact_response.message,
            mode=compact_response.mode,
            diagram=diagram,
            template_suggestions=compact_response.template_suggestions,
            warnings=warnings,
            changes_summary=compact_response.changes_summary,
        )

    def _normalize_invalid_departments(
        self,
        nodes: list[CompactNode],
        departments_by_id: dict[str, str],
        warnings: list[str],
    ) -> None:
        fallback_department_id = next(iter(departments_by_id.keys()))

        for node in nodes:
            if node.department_id not in departments_by_id:
                warnings.append(
                    "La IA usó un departamento inválido en el nodo "
                    f"{node.id}. Se reasignó al primer departamento disponible."
                )
                node.department_id = fallback_department_id

    def _build_lanes(
        self,
        nodes: list[CompactNode],
        departments_by_id: dict[str, str],
    ) -> list[dict[str, Any]]:
        used_department_ids: list[str] = []

        for node in nodes:
            if node.department_id not in used_department_ids:
                used_department_ids.append(node.department_id)

        lane_width = 280
        lane_y = 80
        lane_height = max(760, 180 + len(nodes) * 130)

        lanes: list[dict[str, Any]] = []

        for index, department_id in enumerate(used_department_ids):
            lanes.append(
                {
                    "id": f"lane-{department_id}",
                    "departmentId": department_id,
                    "departmentName": departments_by_id[department_id],
                    "order": index,
                    "x": 80 + index * lane_width,
                    "y": lane_y,
                    "width": lane_width,
                    "height": lane_height,
                }
            )

        return lanes

    def _build_node_cells(
        self,
        nodes: list[CompactNode],
        lanes: list[dict[str, Any]],
        template_by_node_id: dict[str, Any],
    ) -> list[dict[str, Any]]:
        lanes_by_department = {
            lane["departmentId"]: lane
            for lane in lanes
        }

        cells: list[dict[str, Any]] = []

        for index, node in enumerate(nodes):
            lane = lanes_by_department[node.department_id]
            position_y = 160 + index * 120

            if node.type == CompactNodeType.INITIAL:
                cells.append(self._build_initial_node(node, lane, position_y))
                continue

            if node.type == CompactNodeType.FINAL:
                cells.append(self._build_final_node(node, lane, position_y))
                continue

            if node.type == CompactNodeType.DECISION:
                cells.append(self._build_decision_node(node, lane, position_y))
                continue

            template_suggestion = template_by_node_id.get(node.id)
            cells.append(
                self._build_action_node(
                    node=node,
                    lane=lane,
                    position_y=position_y,
                    template_suggestion=template_suggestion,
                )
            )

        return cells

    def _build_initial_node(
        self,
        node: CompactNode,
        lane: dict[str, Any],
        position_y: int,
    ) -> dict[str, Any]:
        return {
            "id": node.id,
            "type": "standard.Circle",
            "position": {
                "x": lane["x"] + 112,
                "y": position_y,
            },
            "size": {
                "width": 36,
                "height": 36,
            },
            "source": None,
            "target": None,
            "attrs": {
                "body": {
                    "fill": "#111827",
                    "stroke": "#111827",
                    "strokeWidth": 2,
                },
                "label": {
                    "text": "",
                },
            },
            "customData": {
                "nombre": node.name,
                "tipo": "INITIAL",
                "laneId": lane["id"],
            },
            "labels": None,
            "vertices": None,
            "router": None,
            "connector": None,
        }

    def _build_final_node(
        self,
        node: CompactNode,
        lane: dict[str, Any],
        position_y: int,
    ) -> dict[str, Any]:
        return {
            "id": node.id,
            "type": "standard.Circle",
            "position": {
                "x": lane["x"] + 112,
                "y": position_y,
            },
            "size": {
                "width": 42,
                "height": 42,
            },
            "source": None,
            "target": None,
            "attrs": {
                "body": {
                    "fill": "#ffffff",
                    "stroke": "#111827",
                    "strokeWidth": 3,
                },
                "inner": {
                    "ref": "body",
                    "refCx": "50%",
                    "refCy": "50%",
                    "refR": "30%",
                    "fill": "#111827",
                    "stroke": "#111827",
                    "strokeWidth": 1,
                },
                "label": {
                    "text": "",
                },
            },
            "customData": {
                "nombre": node.name,
                "tipo": "FINAL",
                "laneId": lane["id"],
            },
            "labels": None,
            "vertices": None,
            "router": None,
            "connector": None,
        }

    def _build_action_node(
        self,
        node: CompactNode,
        lane: dict[str, Any],
        position_y: int,
        template_suggestion: Any,
    ) -> dict[str, Any]:
        template_document_id = ""

        if (
            template_suggestion
            and template_suggestion.strategy
            == TemplateStrategy.USE_EXISTING_TEMPLATE
        ):
            template_document_id = (
                template_suggestion.existing_template_id or ""
            )

        return {
            "id": node.id,
            "type": "standard.Rectangle",
            "position": {
                "x": lane["x"] + 55,
                "y": position_y,
            },
            "size": {
                "width": 170,
                "height": 60,
            },
            "source": None,
            "target": None,
            "attrs": {
                "label": self._build_node_label_attrs(node.name),
            },
            "customData": {
                "tipo": "ACTION",
                "laneId": lane["id"],
                "nombre": node.name,
                "templateDocumentId": template_document_id,
            },
            "labels": None,
            "vertices": None,
            "router": None,
            "connector": None,
        }

    def _build_decision_node(
        self,
        node: CompactNode,
        lane: dict[str, Any],
        position_y: int,
    ) -> dict[str, Any]:
        return {
            "id": node.id,
            "type": "standard.Polygon",
            "position": {
                "x": lane["x"] + 80,
                "y": position_y,
            },
            "size": {
                "width": 120,
                "height": 108,
            },
            "source": None,
            "target": None,
            "attrs": {
                "label": {
                    "text": node.name,
                    "fill": "#111827",
                    "textWrap": {
                        "width": -16,
                        "height": -12,
                        "ellipsis": True,
                    },
                    "textAnchor": "middle",
                    "textVerticalAnchor": "middle",
                    "refX": "50%",
                    "refY": "50%",
                    "xAlignment": "middle",
                    "yAlignment": "middle",
                },
            },
            "customData": {
                "nombre": node.name,
                "tipo": "DECISION",
                "laneId": lane["id"],
                "templateDocumentId": "",
            },
            "labels": None,
            "vertices": None,
            "router": None,
            "connector": None,
        }

    def _build_link_cells(
        self,
        links: list[Any],
        nodes: list[CompactNode],
    ) -> list[dict[str, Any]]:
        node_by_id = {node.id: node for node in nodes}
        cells: list[dict[str, Any]] = []

        for link in links:
            source_node = node_by_id.get(link.source_id)
            link_label = link.label.strip() if link.label else None

            custom_data = {
                "tipo": "CONTROL_FLOW",
            }

            if link_label:
                custom_data["linkLabel"] = link_label

            cells.append(
                {
                    "id": link.id,
                    "type": "standard.Link",
                    "position": None,
                    "size": None,
                    "source": {
                        "id": link.source_id,
                        "port": None,
                    },
                    "target": {
                        "id": link.target_id,
                        "port": None,
                    },
                    "attrs": {
                        "line": self._build_link_line_attrs(),
                    },
                    "customData": custom_data,
                    "labels": self._build_link_labels(
                        link_label=link_label,
                        source_node=source_node,
                    ),
                    "vertices": None,
                    "router": {
                        "name": "manhattan",
                        "args": {
                            "padding": 24,
                            "step": 20,
                        },
                    },
                    "connector": {
                        "name": "rounded",
                        "args": {
                            "radius": 8,
                        },
                    },
                }
            )

        return cells

    def _build_node_label_attrs(self, text: str) -> dict[str, Any]:
        return {
            "refX": "50%",
            "yAlignment": "middle",
            "refY": "50%",
            "textVerticalAnchor": "middle",
            "xAlignment": "middle",
            "textWrap": {
                "width": -16,
                "ellipsis": True,
                "height": -12,
            },
            "text": text,
            "fill": "#111827",
            "textAnchor": "middle",
        }

    def _build_link_line_attrs(self) -> dict[str, Any]:
        return {
            "stroke": "#475569",
            "strokeWidth": 2.5,
            "strokeLinecap": "round",
            "strokeLinejoin": "round",
            "targetMarker": {
                "type": "path",
                "d": "M 10 -5 0 0 10 5 z",
            },
        }

    def _build_link_labels(
        self,
        link_label: str | None,
        source_node: CompactNode | None,
    ) -> list[dict[str, Any]]:
        if not link_label:
            return []

        if source_node and source_node.type != CompactNodeType.DECISION:
            return []

        return [
            {
                "position": 0.5,
                "attrs": {
                    "text": {
                        "text": link_label,
                        "fill": "#111827",
                        "fontSize": 12,
                        "fontWeight": 600,
                        "textAnchor": "middle",
                        "yAlignment": "middle",
                    },
                    "rect": {
                        "fill": "#ffffff",
                        "stroke": "#cbd5e1",
                        "strokeWidth": 1,
                        "rx": 6,
                        "ry": 6,
                    },
                },
            }
        ]

    def _parse_json_response(self, raw_response: str) -> dict[str, Any]:
        cleaned_response = self._clean_json_response(raw_response)

        try:
            parsed = json.loads(cleaned_response)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "message": "La IA no devolvió JSON válido.",
                    "raw_response": raw_response,
                },
            ) from exc

        if not isinstance(parsed, dict):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "message": "La IA debe devolver un objeto JSON principal.",
                    "raw_response": raw_response,
                },
            )

        return parsed

    def _clean_json_response(self, raw_response: str) -> str:
        cleaned = raw_response.strip()

        if cleaned.startswith("```json"):
            cleaned = cleaned.removeprefix("```json").strip()

        if cleaned.startswith("```"):
            cleaned = cleaned.removeprefix("```").strip()

        if cleaned.endswith("```"):
            cleaned = cleaned.removesuffix("```").strip()

        return cleaned

    def _serialize_validation_errors(
        self,
        exc: ValidationError,
    ) -> list[dict[str, Any]]:
        serializable_errors: list[dict[str, Any]] = []

        for error in exc.errors():
            safe_error = {
                "type": error.get("type"),
                "loc": list(error.get("loc", [])),
                "msg": error.get("msg"),
                "input": error.get("input"),
                "url": error.get("url"),
            }

            ctx = error.get("ctx")
            if ctx:
                safe_error["ctx"] = {
                    key: str(value)
                    for key, value in ctx.items()
                }

            serializable_errors.append(safe_error)

        return serializable_errors
