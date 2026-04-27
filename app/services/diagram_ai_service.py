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

        parsed_response = self._normalize_ai_response_before_validation(
            parsed_response=parsed_response,
            request=request,
        )

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
- FORK y JOIN no deben tener template_suggestions.
- Cada DECISION debe estar precedida por un ACTION con SELECT compatible.
- Todo link que salga desde DECISION debe tener label.
- Si usas plantilla existente, strategy debe ser USE_EXISTING_TEMPLATE.
- Si propones plantilla nueva, strategy debe ser CREATE_NEW_TEMPLATE.
- Usa snake_case.
- Si el usuario menciona recepción, solicitud, registro inicial o atención inicial,
  crea un ACTION inicial para esa etapa antes de avanzar a otra área.
- Si propones un SELECT decisorio en una plantilla, crea un DECISION inmediatamente
  después de ese ACTION.
- Si no creas DECISION después de un ACTION, evita poner SELECT decisorio
  en su plantilla.

Reglas críticas de FORK/JOIN:
- Si el usuario pide tareas paralelas, simultáneas, al mismo tiempo, ambas tareas,
  dividir el proceso, unir ramas, fork o join, debes crear nodos FORK y JOIN.
- No representes paralelismo como una secuencia.
- FORK divide el flujo en ramas paralelas.
- JOIN une/sincroniza ramas paralelas.
- El FORK debe tener exactamente 1 entrada y mínimo 2 salidas.
- El JOIN debe tener mínimo 2 entradas y exactamente 1 salida.
- Las tareas paralelas deben salir del mismo FORK y llegar al mismo JOIN.
- Después del JOIN debe continuar el flujo principal.
- FORK y JOIN no son tareas humanas.
- FORK y JOIN no llevan plantillas.
- FORK y JOIN no deben aparecer en template_suggestions.
- En el JSON compacto usa type "FORK" para dividir y type "JOIN" para unir.
- El backend visual convertirá tanto FORK como JOIN a una barra negra
  customData.tipo = "FORK", porque así funciona FlowRoad actualmente.

Ejemplo correcto de paralelismo:
nodes:
- node-fork-preparacion type FORK
- node-preparar-contrato type ACTION
- node-preparar-vehiculo type ACTION
- node-join-preparacion type JOIN

links:
- node-anterior -> node-fork-preparacion
- node-fork-preparacion -> node-preparar-contrato
- node-fork-preparacion -> node-preparar-vehiculo
- node-preparar-contrato -> node-join-preparacion
- node-preparar-vehiculo -> node-join-preparacion
- node-join-preparacion -> node-siguiente

Ejemplo incorrecto:
node-anterior -> node-preparar-contrato -> node-preparar-vehiculo -> node-siguiente
Eso es secuencia, no paralelismo.
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
- FORK y JOIN no deben tener template_suggestions.
- Usa snake_case.

Reglas obligatorias de FORK/JOIN:
- Si el usuario pidió paralelismo, tareas simultáneas, fork, join,
  dividir ramas o unir ramas, debes usar FORK y JOIN.
- No simules paralelismo conectando acciones en secuencia.
- FORK debe tener exactamente 1 entrada y mínimo 2 salidas.
- JOIN debe tener mínimo 2 entradas y exactamente 1 salida.
- Las tareas paralelas deben salir del mismo FORK y llegar al mismo JOIN.
- Después del JOIN debe continuar el flujo principal.
- FORK y JOIN no son ACTION.
- FORK y JOIN no tienen plantilla.
- FORK y JOIN no deben aparecer en template_suggestions.
- Si un FORK tiene menos de 2 salidas, corrígelo.
- Si un JOIN tiene menos de 2 entradas, corrígelo.
- Si un JOIN tiene más de 1 salida, corrígelo.
- Si un FORK tiene más de 1 entrada, corrígelo.

Ejemplo correcto:
anterior -> FORK
FORK -> ACTION rama 1
FORK -> ACTION rama 2
ACTION rama 1 -> JOIN
ACTION rama 2 -> JOIN
JOIN -> siguiente
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

    def _normalize_ai_response_before_validation(
        self,
        parsed_response: dict[str, Any],
        request: DiagramAiRequest,
    ) -> dict[str, Any]:
        diagram = parsed_response.get("diagram")

        if not isinstance(diagram, dict):
            return parsed_response

        nodes = diagram.get("nodes")
        links = diagram.get("links")
        suggestions = parsed_response.get("template_suggestions")

        if not isinstance(nodes, list):
            return parsed_response

        if not isinstance(links, list):
            links = []
            diagram["links"] = links

        if not isinstance(suggestions, list):
            suggestions = []
            parsed_response["template_suggestions"] = suggestions

        changes = parsed_response.get("changes_summary")
        if not isinstance(changes, list):
            changes = []
            parsed_response["changes_summary"] = changes

        warnings = parsed_response.get("warnings")
        if not isinstance(warnings, list):
            warnings = []
            parsed_response["warnings"] = warnings

        self._remove_template_suggestions_for_control_nodes(
            nodes=nodes,
            suggestions=suggestions,
            changes=changes,
        )

        self._reuse_existing_templates_when_possible(
            suggestions=suggestions,
            request=request,
            changes=changes,
        )

        self._downgrade_operational_decision_selects(
            nodes=nodes,
            suggestions=suggestions,
            changes=changes,
        )

        self._fix_decision_action_links(
            nodes=nodes,
            links=links,
            suggestions=suggestions,
            request=request,
            changes=changes,
        )

        self._fix_decision_outgoing_links(
            nodes=nodes,
            links=links,
            suggestions=suggestions,
            request=request,
            changes=changes,
        )

        self._fix_nodes_without_path_to_final(
            nodes=nodes,
            links=links,
            changes=changes,
        )

        return parsed_response

    def _remove_template_suggestions_for_control_nodes(
        self,
        nodes: list[dict[str, Any]],
        suggestions: list[dict[str, Any]],
        changes: list[str],
    ) -> None:
        action_ids = {
            node.get("id")
            for node in nodes
            if isinstance(node, dict) and node.get("type") == "ACTION"
        }

        before = len(suggestions)

        suggestions[:] = [
            suggestion
            for suggestion in suggestions
            if isinstance(suggestion, dict)
            and suggestion.get("node_id") in action_ids
        ]

        removed = before - len(suggestions)
        if removed > 0:
            changes.append(
                f"Se eliminaron {removed} template_suggestions inválidos de nodos de control."
            )

    def _reuse_existing_templates_when_possible(
        self,
        suggestions: list[dict[str, Any]],
        request: DiagramAiRequest,
        changes: list[str],
    ) -> None:
        existing_by_name_and_department: dict[tuple[str, str], Any] = {}

        for template in request.existing_templates:
            key = (
                self._normalize_text(template.name),
                template.department_id or "",
            )
            existing_by_name_and_department[key] = template

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

            key = (
                self._normalize_text(template_name),
                department_id,
            )

            existing_template = existing_by_name_and_department.get(key)

            if not existing_template:
                continue

            suggestion["strategy"] = "USE_EXISTING_TEMPLATE"
            suggestion["existing_template_id"] = existing_template.id
            suggestion["existing_template_name"] = existing_template.name
            suggestion["template"] = None
            suggestion["reason"] = (
                "Se reutilizó una plantilla existente con el mismo nombre "
                "y departamento para evitar duplicados."
            )

            changes.append(
                f"Se reutilizó la plantilla existente '{existing_template.name}' "
                f"para el nodo '{suggestion.get('node_id')}'."
            )

    def _downgrade_operational_decision_selects(
        self,
        nodes: list[dict[str, Any]],
        suggestions: list[dict[str, Any]],
        changes: list[str],
    ) -> None:
        node_by_id = {
            node.get("id"): node
            for node in nodes
            if isinstance(node, dict)
        }

        for suggestion in suggestions:
            if not isinstance(suggestion, dict):
                continue

            if suggestion.get("strategy") != "CREATE_NEW_TEMPLATE":
                continue

            node_id = suggestion.get("node_id")
            node = node_by_id.get(node_id)

            if not isinstance(node, dict):
                continue

            node_name = str(node.get("name") or suggestion.get("node_name") or "")

            if not self._is_operational_action_name(node_name):
                continue

            template = suggestion.get("template")
            if not isinstance(template, dict):
                continue

            fields = template.get("fields")
            if not isinstance(fields, list):
                continue

            changed = False

            for field in fields:
                if not isinstance(field, dict):
                    continue

                if field.get("type") != "SELECT":
                    continue

                options = field.get("options")
                if not isinstance(options, list):
                    continue

                if not self._is_decision_options(options):
                    continue

                field["type"] = "TEXTAREA"
                field["label"] = "Observaciones"
                field["required"] = False
                field["options"] = []
                field["ui_props"] = {
                    "grid_cols": 2,
                }
                changed = True

            if changed:
                changes.append(
                    f"Se cambió un SELECT decisorio por TEXTAREA en el nodo operativo '{node_id}'."
                )

    def _fix_decision_action_links(
        self,
        nodes: list[dict[str, Any]],
        links: list[dict[str, Any]],
        suggestions: list[dict[str, Any]],
        request: DiagramAiRequest,
        changes: list[str],
    ) -> None:
        node_by_id = {
            node.get("id"): node
            for node in nodes
            if isinstance(node, dict)
        }

        suggestions_by_node_id = {
            suggestion.get("node_id"): suggestion
            for suggestion in suggestions
            if isinstance(suggestion, dict)
        }

        for node in nodes:
            if not isinstance(node, dict):
                continue

            if node.get("type") != "ACTION":
                continue

            node_id = str(node.get("id") or "")
            node_name = str(node.get("name") or "")

            if not node_id:
                continue

            suggestion = suggestions_by_node_id.get(node_id)
            if not isinstance(suggestion, dict):
                continue

            option_labels = self._get_decision_option_labels_from_suggestion(
                suggestion=suggestion,
                request=request,
            )

            if len(option_labels) < 2:
                continue

            if self._is_operational_action_name(node_name):
                continue

            outgoing = self._get_outgoing_links(links, node_id)

            already_has_decision_after = any(
                node_by_id.get(link.get("target_id"), {}).get("type") == "DECISION"
                for link in outgoing
                if isinstance(link, dict)
            )

            if already_has_decision_after:
                continue

            matching_decision = self._find_best_matching_decision(
                action_node=node,
                nodes=nodes,
                links=links,
            )

            if matching_decision:
                decision_id = str(matching_decision.get("id"))

                links[:] = [
                    link
                    for link in links
                    if not (
                        isinstance(link, dict)
                        and link.get("source_id") == node_id
                        and node_by_id.get(link.get("target_id"), {}).get("type") != "DECISION"
                    )
                ]

                if not self._link_exists(links, node_id, decision_id):
                    links.append(
                        {
                            "id": self._build_link_id(node_id, decision_id),
                            "source_id": node_id,
                            "target_id": decision_id,
                            "label": None,
                        }
                    )

                changes.append(
                    f"Se conectó el ACTION '{node_id}' con la DECISION '{decision_id}'."
                )
                continue

            if self._is_decision_action_name(node_name):
                final_id = self._get_first_final_id(nodes)
                if not final_id:
                    continue

                old_targets = [
                    str(link.get("target_id"))
                    for link in outgoing
                    if isinstance(link, dict)
                    and node_by_id.get(link.get("target_id"), {}).get("type") != "DECISION"
                ]

                links[:] = [
                    link
                    for link in links
                    if not (
                        isinstance(link, dict)
                        and link.get("source_id") == node_id
                    )
                ]

                decision_id = f"node-decision-{self._slugify(node_name)}"

                if decision_id not in node_by_id:
                    nodes.append(
                        {
                            "id": decision_id,
                            "type": "DECISION",
                            "name": self._build_decision_name_from_action(node_name),
                            "department_id": node.get("department_id"),
                        }
                    )
                    node_by_id[decision_id] = nodes[-1]

                links.append(
                    {
                        "id": self._build_link_id(node_id, decision_id),
                        "source_id": node_id,
                        "target_id": decision_id,
                        "label": None,
                    }
                )

                positive_target = old_targets[0] if old_targets else final_id
                negative_target = final_id

                links.append(
                    {
                        "id": self._build_link_id(decision_id, positive_target, option_labels[0]),
                        "source_id": decision_id,
                        "target_id": positive_target,
                        "label": option_labels[0],
                    }
                )
                links.append(
                    {
                        "id": self._build_link_id(decision_id, negative_target, option_labels[1]),
                        "source_id": decision_id,
                        "target_id": negative_target,
                        "label": option_labels[1],
                    }
                )

                changes.append(
                    f"Se creó una DECISION automática después del ACTION '{node_id}'."
                )

    def _fix_decision_outgoing_links(
        self,
        nodes: list[dict[str, Any]],
        links: list[dict[str, Any]],
        suggestions: list[dict[str, Any]],
        request: DiagramAiRequest,
        changes: list[str],
    ) -> None:
        suggestions_by_node_id = {
            suggestion.get("node_id"): suggestion
            for suggestion in suggestions
            if isinstance(suggestion, dict)
        }

        final_id = self._get_first_final_id(nodes)
        if not final_id:
            return

        for decision in nodes:
            if not isinstance(decision, dict):
                continue

            if decision.get("type") != "DECISION":
                continue

            decision_id = str(decision.get("id") or "")
            if not decision_id:
                continue

            incoming_action_id = self._get_single_incoming_action_id(
                decision_id=decision_id,
                nodes=nodes,
                links=links,
            )

            option_labels = ["Si", "No"]

            if incoming_action_id:
                suggestion = suggestions_by_node_id.get(incoming_action_id)
                if isinstance(suggestion, dict):
                    detected_options = self._get_decision_option_labels_from_suggestion(
                        suggestion=suggestion,
                        request=request,
                    )
                    if len(detected_options) >= 2:
                        option_labels = detected_options[:2]

            outgoing = self._get_outgoing_links(links, decision_id)

            if len(outgoing) >= 2:
                for index, link in enumerate(outgoing[:2]):
                    if not str(link.get("label") or "").strip():
                        link["label"] = option_labels[index]

                current_labels = {
                    self._normalize_text(str(link.get("label") or ""))
                    for link in outgoing[:2]
                    if isinstance(link, dict)
                }

                allowed_labels = {
                    self._normalize_text(option)
                    for option in option_labels
                }

                if not current_labels.issubset(allowed_labels):
                    for index, link in enumerate(outgoing[:2]):
                        link["label"] = option_labels[index]

                    changes.append(
                        f"Se alinearon los labels de la DECISION '{decision_id}' "
                        "con el SELECT anterior."
                    )

                continue

            if len(outgoing) == 1:
                existing_label = str(outgoing[0].get("label") or "").strip()
                if not existing_label:
                    outgoing[0]["label"] = option_labels[0]

                missing_label = option_labels[1]
                links.append(
                    {
                        "id": self._build_link_id(decision_id, final_id, missing_label),
                        "source_id": decision_id,
                        "target_id": final_id,
                        "label": missing_label,
                    }
                )

                changes.append(
                    f"Se agregó una segunda salida a la DECISION '{decision_id}'."
                )
                continue

            if len(outgoing) == 0:
                links.append(
                    {
                        "id": self._build_link_id(decision_id, final_id, option_labels[0]),
                        "source_id": decision_id,
                        "target_id": final_id,
                        "label": option_labels[0],
                    }
                )
                links.append(
                    {
                        "id": self._build_link_id(decision_id, final_id, option_labels[1]),
                        "source_id": decision_id,
                        "target_id": final_id,
                        "label": option_labels[1],
                    }
                )

                changes.append(
                    f"Se agregaron salidas automáticas a la DECISION '{decision_id}'."
                )

    def _fix_nodes_without_path_to_final(
        self,
        nodes: list[dict[str, Any]],
        links: list[dict[str, Any]],
        changes: list[str],
    ) -> None:
        final_id = self._get_first_final_id(nodes)
        if not final_id:
            return

        outgoing = self._build_outgoing_from_links(links)

        for node in nodes:
            if not isinstance(node, dict):
                continue

            node_id = str(node.get("id") or "")
            node_type = node.get("type")

            if not node_id:
                continue

            if node_type not in {"ACTION", "FORK", "JOIN"}:
                continue

            reachable = self._reachable_from(node_id, outgoing)

            if final_id in reachable:
                continue

            if self._link_exists(links, node_id, final_id):
                continue

            links.append(
                {
                    "id": self._build_link_id(node_id, final_id),
                    "source_id": node_id,
                    "target_id": final_id,
                    "label": None,
                }
            )

            outgoing.setdefault(node_id, []).append(final_id)

            changes.append(
                f"Se conectó el nodo '{node_id}' al FINAL para asegurar cierre del flujo."
            )

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

        action_node_ids = {
            node.get("id")
            for node in nodes
            if isinstance(node, dict) and node.get("type") == "ACTION"
        }

        suggestions = [
            suggestion
            for suggestion in suggestions
            if isinstance(suggestion, dict)
            and suggestion.get("node_id") in action_node_ids
        ]

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
        normalized_safe = self._normalize_text(node_name)

        if self._is_operational_action_name(normalized_safe):
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
                    "type": "TEXTAREA",
                    "label": "Observaciones",
                    "required": False,
                    "options": [],
                    "ui_props": {
                        "grid_cols": 2,
                    },
                },
            ]

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

        if "document" in normalized_name or "documentación" in normalized_name:
            return [
                {
                    "type": "SELECT",
                    "label": "¿Documentación completa?",
                    "required": True,
                    "options": [
                        {
                            "label": "Completo",
                            "value": "completo",
                        },
                        {
                            "label": "Incompleto",
                            "value": "incompleto",
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

            if node.type in {CompactNodeType.FORK, CompactNodeType.JOIN}:
                cells.append(self._build_fork_join_node(node, lane, position_y))
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

    def _build_fork_join_node(
        self,
        node: CompactNode,
        lane: dict[str, Any],
        position_y: int,
    ) -> dict[str, Any]:
        return {
            "id": node.id,
            "type": "standard.Rectangle",
            "position": {
                "x": lane["x"] + 70,
                "y": position_y,
            },
            "size": {
                "width": 140,
                "height": 18,
            },
            "source": None,
            "target": None,
            "attrs": {
                "body": {
                    "fill": "#111827",
                    "stroke": "#111827",
                    "strokeWidth": 1,
                    "rx": 4,
                    "ry": 4,
                },
                "label": {
                    "text": "",
                    "fill": "#111827",
                },
            },
            "customData": {
                "nombre": "Fork/Join",
                "tipo": "FORK",
                "laneId": lane["id"],
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

    def _get_outgoing_links(
        self,
        links: list[dict[str, Any]],
        node_id: str,
    ) -> list[dict[str, Any]]:
        return [
            link
            for link in links
            if isinstance(link, dict) and link.get("source_id") == node_id
        ]

    def _get_incoming_links(
        self,
        links: list[dict[str, Any]],
        node_id: str,
    ) -> list[dict[str, Any]]:
        return [
            link
            for link in links
            if isinstance(link, dict) and link.get("target_id") == node_id
        ]

    def _get_single_incoming_action_id(
        self,
        decision_id: str,
        nodes: list[dict[str, Any]],
        links: list[dict[str, Any]],
    ) -> str | None:
        node_by_id = {
            node.get("id"): node
            for node in nodes
            if isinstance(node, dict)
        }

        incoming_actions = [
            str(link.get("source_id"))
            for link in self._get_incoming_links(links, decision_id)
            if node_by_id.get(link.get("source_id"), {}).get("type") == "ACTION"
        ]

        if len(incoming_actions) == 1:
            return incoming_actions[0]

        return None

    def _find_best_matching_decision(
        self,
        action_node: dict[str, Any],
        nodes: list[dict[str, Any]],
        links: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        action_name = self._normalize_text(str(action_node.get("name") or ""))
        best_decision: dict[str, Any] | None = None
        best_score = 0

        for node in nodes:
            if not isinstance(node, dict):
                continue

            if node.get("type") != "DECISION":
                continue

            decision_id = str(node.get("id") or "")
            decision_name = self._normalize_text(str(node.get("name") or ""))

            incoming_action_id = self._get_single_incoming_action_id(
                decision_id=decision_id,
                nodes=nodes,
                links=links,
            )

            if incoming_action_id:
                continue

            score = self._similarity_score(action_name, decision_name)

            if score > best_score:
                best_score = score
                best_decision = node

        if best_score <= 0:
            return None

        return best_decision

    def _get_decision_option_labels_from_suggestion(
        self,
        suggestion: dict[str, Any],
        request: DiagramAiRequest,
    ) -> list[str]:
        if suggestion.get("strategy") == "USE_EXISTING_TEMPLATE":
            existing_template_id = suggestion.get("existing_template_id")
            if not existing_template_id:
                return []

            for template in request.existing_templates:
                if template.id != existing_template_id:
                    continue

                for field in template.fields:
                    if field.type.value != "SELECT":
                        continue

                    options = [
                        {
                            "label": option.label,
                            "value": option.value,
                        }
                        for option in field.options
                    ]

                    if self._is_decision_options(options):
                        return [option.label for option in field.options]

            return []

        template = suggestion.get("template")
        if not isinstance(template, dict):
            return []

        fields = template.get("fields")
        if not isinstance(fields, list):
            return []

        for field in fields:
            if not isinstance(field, dict):
                continue

            if field.get("type") != "SELECT":
                continue

            options = field.get("options")
            if not isinstance(options, list):
                continue

            if self._is_decision_options(options):
                return [
                    str(option.get("label") or option.get("value") or "")
                    for option in options
                    if isinstance(option, dict)
                ]

        return []

    def _is_decision_options(
        self,
        options: list[dict[str, Any]],
    ) -> bool:
        values: set[str] = set()

        for option in options:
            if not isinstance(option, dict):
                continue

            label = str(option.get("label") or "")
            value = str(option.get("value") or "")

            values.add(self._normalize_text(label))
            values.add(self._normalize_text(value))

        valid_pairs = [
            {"si", "no"},
            {"aprobado", "rechazado"},
            {"aceptado", "rechazado"},
            {"disponible", "no disponible"},
            {"completo", "incompleto"},
        ]

        return any(pair.issubset(values) for pair in valid_pairs)

    def _is_operational_action_name(self, name: str) -> bool:
        normalized = self._normalize_text(name)

        decision_keywords = [
            "verificar",
            "validar",
            "revisar",
            "confirmar",
            "aprobar",
            "evaluar",
            "comprobar",
        ]

        if any(keyword in normalized for keyword in decision_keywords):
            return False

        operational_keywords = [
            "solicitar correccion",
            "correccion",
            "corregir",
            "ajustar",
            "registrar",
            "preparar",
            "notificar",
            "enviar",
            "generar",
            "emitir",
            "entregar",
            "recepcion",
            "capturar",
        ]

        return any(keyword in normalized for keyword in operational_keywords)

    def _is_decision_action_name(self, name: str) -> bool:
        normalized = self._normalize_text(name)

        keywords = [
            "verificar",
            "validar",
            "revisar",
            "confirmar",
            "aprobar",
            "evaluar",
            "comprobar",
            "disponibilidad",
            "documentacion",
            "listo",
        ]

        return any(keyword in normalized for keyword in keywords)

    def _build_decision_name_from_action(self, action_name: str) -> str:
        normalized = self._normalize_text(action_name)

        if "document" in normalized:
            return "¿Documentación completa?"

        if "dispon" in normalized:
            return "¿Está disponible?"

        if "acept" in normalized:
            return "¿Cliente acepta?"

        if "listo" in normalized or "entrega" in normalized:
            return "¿Todo listo?"

        return f"¿{action_name}?"

    def _get_first_final_id(
        self,
        nodes: list[dict[str, Any]],
    ) -> str | None:
        for node in nodes:
            if not isinstance(node, dict):
                continue

            if node.get("type") == "FINAL":
                node_id = node.get("id")
                return str(node_id) if node_id else None

        return None

    def _build_outgoing_from_links(
        self,
        links: list[dict[str, Any]],
    ) -> dict[str, list[str]]:
        outgoing: dict[str, list[str]] = {}

        for link in links:
            if not isinstance(link, dict):
                continue

            source_id = link.get("source_id")
            target_id = link.get("target_id")

            if not source_id or not target_id:
                continue

            outgoing.setdefault(str(source_id), []).append(str(target_id))

        return outgoing

    def _reachable_from(
        self,
        start_id: str,
        outgoing: dict[str, list[str]],
    ) -> set[str]:
        visited: set[str] = set()
        queue: list[str] = [start_id]

        while queue:
            current = queue.pop(0)

            if current in visited:
                continue

            visited.add(current)

            for next_id in outgoing.get(current, []):
                if next_id not in visited:
                    queue.append(next_id)

        return visited

    def _link_exists(
        self,
        links: list[dict[str, Any]],
        source_id: str,
        target_id: str,
    ) -> bool:
        return any(
            isinstance(link, dict)
            and link.get("source_id") == source_id
            and link.get("target_id") == target_id
            for link in links
        )

    def _build_link_id(
        self,
        source_id: str,
        target_id: str,
        label: str | None = None,
    ) -> str:
        raw = f"link-{source_id}-{target_id}"

        if label:
            raw = f"{raw}-{label}"

        return self._slugify(raw)

    def _similarity_score(self, left: str, right: str) -> int:
        left_words = {
            word
            for word in left.split()
            if len(word) >= 4
        }
        right_words = {
            word
            for word in right.split()
            if len(word) >= 4
        }

        return len(left_words.intersection(right_words))

    def _slugify(self, value: str) -> str:
        normalized = self._normalize_text(value)
        normalized = normalized.replace("¿", "").replace("?", "")
        normalized = normalized.replace("/", " ")
        normalized = normalized.replace("_", " ")
        parts = [
            part
            for part in normalized.split()
            if part
        ]

        return "-".join(parts)[:90] or "item"

    def _normalize_text(self, value: str) -> str:
        normalized = value.strip().lower()
        normalized = normalized.replace("sí", "si")
        normalized = normalized.replace("á", "a")
        normalized = normalized.replace("é", "e")
        normalized = normalized.replace("í", "i")
        normalized = normalized.replace("ó", "o")
        normalized = normalized.replace("ú", "u")
        normalized = normalized.replace("ñ", "n")
        normalized = normalized.replace("¿", "")
        normalized = normalized.replace("?", "")
        normalized = " ".join(normalized.split())
        return normalized

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