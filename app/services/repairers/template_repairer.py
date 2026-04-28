from typing import Any
from app.schemas.diagram_ai_schemas import DiagramAiRequest
from app.services.repairers.base_repairer import BaseRepairer


class TemplateRepairer(BaseRepairer):
    def reuse_existing_templates_by_name(
        self,
        suggestions: list[dict[str, Any]],
        request: DiagramAiRequest,
        changes: list[str],
    ) -> None:
        existing_by_name_and_department: dict[tuple[str, str], Any] = {}
        existing_by_name: dict[str, Any] = {}

        for template in request.existing_templates:
            normalized_name = self._normalize_text(template.name)
            department_id = template.department_id or ""

            existing_by_name_and_department[(normalized_name, department_id)] = template
            existing_by_name[normalized_name] = template

        for suggestion in suggestions:
            if not isinstance(suggestion, dict):
                continue

            if suggestion.get("strategy") != "CREATE_NEW_TEMPLATE":
                continue

            template = suggestion.get("template")
            if not isinstance(template, dict):
                continue

            template_name = str(template.get("name") or "")
            department_id = str(template.get("department_id") or "")

            normalized_name = self._normalize_text(template_name)

            existing_template = existing_by_name_and_department.get(
                (normalized_name, department_id),
            )

            if not existing_template:
                existing_template = existing_by_name.get(normalized_name)

            if not existing_template:
                continue

            suggestion["strategy"] = "USE_EXISTING_TEMPLATE"
            suggestion["existing_template_id"] = existing_template.id
            suggestion["existing_template_name"] = existing_template.name
            suggestion["template"] = None
            suggestion["reason"] = (
                "Se reutilizó una plantilla existente detectada automáticamente "
                "para evitar duplicados."
            )

            changes.append(
                f"Se reutilizó la plantilla existente '{existing_template.name}' "
                f"para el nodo '{suggestion.get('node_id')}'."
            )
