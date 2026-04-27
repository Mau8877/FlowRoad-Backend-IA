from typing import Any

from app.schemas.diagram_ai_schemas import DiagramAiRequest


class DiagramAiTemplateRepairer:
    def repair_missing_template_suggestions(
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
                        "fields": self.build_default_template_fields(
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

    def build_default_template_fields(
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