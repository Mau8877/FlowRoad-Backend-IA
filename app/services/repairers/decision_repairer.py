from typing import Any
from app.schemas.diagram_ai_schemas import DiagramAiRequest
from app.services.repairers.base_repairer import BaseRepairer


class DecisionRepairer(BaseRepairer):
    def ensure_decisions_have_action_before(
        self,
        nodes: list[dict[str, Any]],
        links: list[dict[str, Any]],
        changes: list[str],
    ) -> None:
        node_by_id = self._build_node_by_id(nodes)

        for index, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue

            if node.get("type") != "DECISION":
                continue

            decision_id = str(node.get("id") or "")
            if not decision_id:
                continue

            incoming_action = self._get_incoming_action_id(
                decision_id=decision_id,
                links=links,
                node_by_id=node_by_id,
            )

            if incoming_action:
                continue

            previous_action = self._find_previous_action_node(
                nodes=nodes,
                before_index=index,
            )

            if not previous_action:
                continue

            previous_action_id = str(previous_action.get("id") or "")
            if not previous_action_id:
                continue

            if self._has_link(links, previous_action_id, decision_id):
                continue

            links.append(
                {
                    "id": self._build_link_id(previous_action_id, decision_id),
                    "source_id": previous_action_id,
                    "target_id": decision_id,
                    "label": None,
                }
            )

            changes.append(
                f"Se conectó automáticamente el ACTION '{previous_action_id}' "
                f"antes de la DECISION '{decision_id}'."
            )

    def create_missing_decisions_after_decisive_actions(
        self,
        nodes: list[dict[str, Any]],
        links: list[dict[str, Any]],
        suggestions: list[dict[str, Any]],
        request: DiagramAiRequest,
        changes: list[str],
    ) -> None:
        final_id = self._get_first_final_id(nodes)
        if not final_id:
            return

        suggestions_by_node_id = {
            suggestion.get("node_id"): suggestion
            for suggestion in suggestions
            if isinstance(suggestion, dict)
        }

        index = 0

        while index < len(nodes):
            node = nodes[index]

            if not isinstance(node, dict):
                index += 1
                continue

            if node.get("type") != "ACTION":
                index += 1
                continue

            node_id = str(node.get("id") or "")
            node_name = str(node.get("name") or "")

            if not node_id:
                index += 1
                continue

            suggestion = suggestions_by_node_id.get(node_id)
            if not isinstance(suggestion, dict):
                index += 1
                continue

            option_labels = self._get_decisive_select_labels(
                suggestion=suggestion,
                request=request,
            )

            if len(option_labels) < 2:
                index += 1
                continue

            outgoing_links = self._get_outgoing_links(links, node_id)
            node_by_id = self._build_node_by_id(nodes)

            has_decision_after = any(
                node_by_id.get(link.get("target_id"), {}).get("type") == "DECISION"
                for link in outgoing_links
                if isinstance(link, dict)
            )

            if has_decision_after:
                index += 1
                continue

            old_targets = [
                str(link.get("target_id"))
                for link in outgoing_links
                if isinstance(link, dict) and link.get("target_id")
            ]

            links[:] = [
                link
                for link in links
                if not (
                    isinstance(link, dict)
                    and link.get("source_id") == node_id
                )
            ]

            decision_id = self._build_decision_id(node_id, node_name)

            if decision_id not in self._build_node_by_id(nodes):
                decision_node = {
                    "id": decision_id,
                    "type": "DECISION",
                    "name": self._build_decision_name(node_name),
                    "department_id": node.get("department_id"),
                }

                nodes.insert(index + 1, decision_node)

            positive_target = old_targets[0] if old_targets else final_id
            negative_target = final_id

            links.append(
                {
                    "id": self._build_link_id(node_id, decision_id),
                    "source_id": node_id,
                    "target_id": decision_id,
                    "label": None,
                }
            )

            links.append(
                {
                    "id": self._build_link_id(
                        decision_id,
                        positive_target,
                        option_labels[0],
                    ),
                    "source_id": decision_id,
                    "target_id": positive_target,
                    "label": option_labels[0],
                }
            )

            links.append(
                {
                    "id": self._build_link_id(
                        decision_id,
                        negative_target,
                        option_labels[1],
                    ),
                    "source_id": decision_id,
                    "target_id": negative_target,
                    "label": option_labels[1],
                }
            )

            changes.append(
                f"Se creó automáticamente la DECISION '{decision_id}' "
                f"después del ACTION '{node_id}'."
            )

            index += 2

    def ensure_decisions_have_two_outputs(
        self,
        nodes: list[dict[str, Any]],
        links: list[dict[str, Any]],
        suggestions: list[dict[str, Any]],
        request: DiagramAiRequest,
        changes: list[str],
    ) -> None:
        final_id = self._get_first_final_id(nodes)
        if not final_id:
            return

        node_by_id = self._build_node_by_id(nodes)
        suggestions_by_node_id = {
            suggestion.get("node_id"): suggestion
            for suggestion in suggestions
            if isinstance(suggestion, dict)
        }

        for node in nodes:
            if not isinstance(node, dict):
                continue

            if node.get("type") != "DECISION":
                continue

            decision_id = str(node.get("id") or "")
            if not decision_id:
                continue

            option_labels = ["Si", "No"]

            incoming_action_id = self._get_incoming_action_id(
                decision_id=decision_id,
                links=links,
                node_by_id=node_by_id,
            )

            if incoming_action_id:
                suggestion = suggestions_by_node_id.get(incoming_action_id)

                if isinstance(suggestion, dict):
                    detected_labels = self._get_decisive_select_labels(
                        suggestion=suggestion,
                        request=request,
                    )

                    if len(detected_labels) >= 2:
                        option_labels = detected_labels[:2]

            outgoing_links = self._get_outgoing_links(links, decision_id)

            if len(outgoing_links) >= 2:
                for index, link in enumerate(outgoing_links[:2]):
                    if not str(link.get("label") or "").strip():
                        link["label"] = option_labels[index]
                continue

            if len(outgoing_links) == 1:
                if not str(outgoing_links[0].get("label") or "").strip():
                    outgoing_links[0]["label"] = option_labels[0]

                links.append(
                    {
                        "id": self._build_link_id(
                            decision_id,
                            final_id,
                            option_labels[1],
                        ),
                        "source_id": decision_id,
                        "target_id": final_id,
                        "label": option_labels[1],
                    }
                )

                changes.append(
                    f"Se agregó una segunda salida automática a la DECISION "
                    f"'{decision_id}'."
                )
                continue

            links.append(
                {
                    "id": self._build_link_id(
                        decision_id,
                        final_id,
                        option_labels[0],
                    ),
                    "source_id": decision_id,
                    "target_id": final_id,
                    "label": option_labels[0],
                }
            )

            links.append(
                {
                    "id": self._build_link_id(
                        decision_id,
                        final_id,
                        option_labels[1],
                    ),
                    "source_id": decision_id,
                    "target_id": final_id,
                    "label": option_labels[1],
                }
            )

            changes.append(
                f"Se agregaron dos salidas automáticas a la DECISION "
                f"'{decision_id}'."
            )

    def ensure_previous_actions_have_compatible_select(
        self,
        nodes: list[dict[str, Any]],
        links: list[dict[str, Any]],
        suggestions: list[dict[str, Any]],
        request: DiagramAiRequest,
        changes: list[str],
    ) -> None:
        node_by_id = self._build_node_by_id(nodes)

        suggestions_by_node_id = {
            suggestion.get("node_id"): suggestion
            for suggestion in suggestions
            if isinstance(suggestion, dict)
        }

        for node in nodes:
            if not isinstance(node, dict):
                continue

            if node.get("type") != "DECISION":
                continue

            decision_id = str(node.get("id") or "")
            if not decision_id:
                continue

            previous_action_id = self._get_incoming_action_id(
                decision_id=decision_id,
                links=links,
                node_by_id=node_by_id,
            )

            if not previous_action_id:
                continue

            previous_action = node_by_id.get(previous_action_id)
            if not previous_action:
                continue

            decision_labels = self._get_decision_labels_from_links(
                decision_id=decision_id,
                links=links,
            )

            if len(decision_labels) < 2:
                decision_labels = ["Si", "No"]

            suggestion = suggestions_by_node_id.get(previous_action_id)

            if isinstance(suggestion, dict):
                current_labels = self._get_decisive_select_labels(
                    suggestion=suggestion,
                    request=request,
                )

                normalized_current = {
                    self._normalize_text(label)
                    for label in current_labels
                }

                normalized_required = {
                    self._normalize_text(label)
                    for label in decision_labels
                }

                if normalized_required.issubset(normalized_current):
                    continue

            repaired_suggestion = self._build_decision_template_suggestion(
                action_node=previous_action,
                decision_node=node,
                decision_labels=decision_labels,
                request=request,
            )

            if isinstance(suggestion, dict):
                suggestion.clear()
                suggestion.update(repaired_suggestion)
            else:
                suggestions.append(repaired_suggestion)

            changes.append(
                f"Se creó una plantilla con SELECT compatible para el ACTION "
                f"'{previous_action_id}' antes de la DECISION '{decision_id}'."
            )

    def _get_incoming_action_id(
        self,
        decision_id: str,
        links: list[dict[str, Any]],
        node_by_id: dict[str, dict[str, Any]],
    ) -> str | None:
        incoming_actions = [
            str(link.get("source_id"))
            for link in self._get_incoming_links(links, decision_id)
            if node_by_id.get(str(link.get("source_id")), {}).get("type") == "ACTION"
        ]

        if len(incoming_actions) == 1:
            return incoming_actions[0]

        return None

    def _find_previous_action_node(
        self,
        nodes: list[dict[str, Any]],
        before_index: int,
    ) -> dict[str, Any] | None:
        for index in range(before_index - 1, -1, -1):
            node = nodes[index]

            if not isinstance(node, dict):
                continue

            if node.get("type") == "ACTION":
                return node

        return None

    def _get_decision_labels_from_links(
        self,
        decision_id: str,
        links: list[dict[str, Any]],
    ) -> list[str]:
        labels: list[str] = []

        for link in links:
            if not isinstance(link, dict):
                continue

            if link.get("source_id") != decision_id:
                continue

            label = str(link.get("label") or "").strip()

            if label:
                labels.append(label)

        unique_labels: list[str] = []
        used_normalized: set[str] = set()

        for label in labels:
            normalized = self._normalize_text(label)

            if normalized in used_normalized:
                continue

            unique_labels.append(label)
            used_normalized.add(normalized)

        return unique_labels

    def _build_decision_template_suggestion(
        self,
        action_node: dict[str, Any],
        decision_node: dict[str, Any],
        decision_labels: list[str],
        request: DiagramAiRequest,
    ) -> dict[str, Any]:
        action_id = str(action_node.get("id") or "")
        action_name = str(action_node.get("name") or "Tarea")
        department_id = str(action_node.get("department_id") or "")
        decision_name = str(decision_node.get("name") or "Decisión")

        department_name = self._get_department_name(
            department_id=department_id,
            request=request,
        )

        normalized_action_name = self._normalize_text(action_name)
        normalized_decision_name = self._normalize_text(decision_name)

        select_label = self._build_select_label_for_decision(
            normalized_action_name=normalized_action_name,
            normalized_decision_name=normalized_decision_name,
            fallback=decision_name,
        )

        safe_labels = decision_labels[:2]

        if len(safe_labels) < 2:
            safe_labels = ["Si", "No"]

        return {
            "node_id": action_id,
            "node_name": action_name,
            "strategy": "CREATE_NEW_TEMPLATE",
            "existing_template_id": None,
            "existing_template_name": None,
            "template": {
                "name": f"{action_name} - Decisión",
                "description": (
                    f"Plantilla generada automáticamente para permitir la "
                    f"decisión: {decision_name}."
                ),
                "department_id": department_id,
                "department_name": department_name,
                "fields": [
                    {
                        "type": "SELECT",
                        "label": select_label,
                        "required": True,
                        "options": [
                            {
                                "label": safe_labels[0],
                                "value": self._normalize_text(safe_labels[0]),
                            },
                            {
                                "label": safe_labels[1],
                                "value": self._normalize_text(safe_labels[1]),
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
                ],
            },
            "reason": (
                "Se generó automáticamente porque este ACTION precede una "
                "DECISION y necesita un SELECT compatible con sus salidas."
            ),
        }

    def _build_select_label_for_decision(
        self,
        normalized_action_name: str,
        normalized_decision_name: str,
        fallback: str,
    ) -> str:
        text = f"{normalized_action_name} {normalized_decision_name}"

        if "repuesto" in text:
            return "¿Requiere repuesto?"

        if "aprob" in text:
            return "¿Cliente aprueba?"

        if "acept" in text:
            return "¿Cliente acepta?"

        if "avanza" in text or "perfil" in text or "candidato" in text:
            return "¿Candidato avanza?"

        if "dispon" in text:
            return "¿Está disponible?"

        if "document" in text:
            return "¿Documentación completa?"

        if "listo" in text:
            return "¿Está listo?"

        clean_fallback = fallback.strip()

        if clean_fallback.startswith("¿"):
            return clean_fallback

        return f"¿{clean_fallback}?"

    def _get_department_name(
        self,
        department_id: str,
        request: DiagramAiRequest,
    ) -> str | None:
        for department in request.available_departments:
            if department.id == department_id:
                return department.name

        return None

    def _get_decisive_select_labels(
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

                    if self._are_decisive_options(options):
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

            if self._are_decisive_options(options):
                return [
                    str(option.get("label") or option.get("value") or "")
                    for option in options
                    if isinstance(option, dict)
                ]

        return []

    def _are_decisive_options(
        self,
        options: list[dict[str, Any]],
    ) -> bool:
        values: set[str] = set()

        for option in options:
            if not isinstance(option, dict):
                continue

            values.add(self._normalize_text(str(option.get("label") or "")))
            values.add(self._normalize_text(str(option.get("value") or "")))

        valid_pairs = [
            {"si", "no"},
            {"aprobado", "rechazado"},
            {"aceptado", "rechazado"},
            {"disponible", "no disponible"},
            {"completo", "incompleto"},
        ]

        return any(pair.issubset(values) for pair in valid_pairs)

    def _build_decision_id(self, action_id: str, action_name: str) -> str:
        slug = self._slugify(action_name or action_id)
        return f"node-decision-{slug}"

    def _build_decision_name(self, action_name: str) -> str:
        normalized = self._normalize_text(action_name)

        if "dispon" in normalized:
            return "¿Está disponible?"

        if "acept" in normalized or "confirm" in normalized:
            return "¿Cliente acepta?"

        if "document" in normalized:
            return "¿Documentación completa?"

        if "listo" in normalized:
            return "¿Está listo?"

        if "repuesto" in normalized:
            return "¿Requiere repuesto?"

        if "aprob" in normalized:
            return "¿Cliente aprueba?"

        if "avanza" in normalized or "perfil" in normalized or "candidato" in normalized:
            return "¿Candidato avanza?"

        return f"¿{action_name}?"
