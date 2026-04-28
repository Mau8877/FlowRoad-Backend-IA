from collections import defaultdict, deque

from app.schemas.diagram_ai_schemas import (
    CompactDiagram,
    CompactNode,
    CompactNodeType,
    ExistingTemplateContext,
    FieldType,
    TemplateStrategy,
    TemplateSuggestion,
)


class DiagramSemanticValidator:
    def validate(
        self,
        diagram: CompactDiagram,
        template_suggestions: list[TemplateSuggestion],
        existing_templates: list[ExistingTemplateContext] | None = None,
    ) -> list[str]:
        errors: list[str] = []

        nodes_by_id = {node.id: node for node in diagram.nodes}
        outgoing = self._build_outgoing(diagram)
        incoming = self._build_incoming(diagram)

        existing_templates_by_id = {
            template.id: template
            for template in existing_templates or []
        }

        errors.extend(
            self._validate_decision_outgoing_links(diagram, outgoing)
        )
        errors.extend(
            self._validate_fork_topology(
                diagram=diagram,
                incoming=incoming,
                outgoing=outgoing,
            )
        )
        errors.extend(
            self._validate_decision_previous_action_select(
                diagram=diagram,
                template_suggestions=template_suggestions,
                incoming=incoming,
                nodes_by_id=nodes_by_id,
                existing_templates_by_id=existing_templates_by_id,
            )
        )
        errors.extend(
            self._validate_action_select_has_decision_after(
                diagram=diagram,
                template_suggestions=template_suggestions,
                outgoing=outgoing,
                nodes_by_id=nodes_by_id,
                existing_templates_by_id=existing_templates_by_id,
            )
        )
        errors.extend(
            self._validate_no_orphan_nodes(
                diagram=diagram,
                outgoing=outgoing,
            )
        )
        errors.extend(
            self._validate_every_action_reaches_final(
                diagram=diagram,
                outgoing=outgoing,
            )
        )

        return errors

    def _build_outgoing(
        self,
        diagram: CompactDiagram,
    ) -> dict[str, list[str]]:
        outgoing: dict[str, list[str]] = defaultdict(list)

        for link in diagram.links:
            outgoing[link.source_id].append(link.target_id)

        return outgoing

    def _build_incoming(
        self,
        diagram: CompactDiagram,
    ) -> dict[str, list[str]]:
        incoming: dict[str, list[str]] = defaultdict(list)

        for link in diagram.links:
            incoming[link.target_id].append(link.source_id)

        return incoming

    def _validate_decision_outgoing_links(
        self,
        diagram: CompactDiagram,
        outgoing: dict[str, list[str]],
    ) -> list[str]:
        errors: list[str] = []

        decision_ids = {
            node.id
            for node in diagram.nodes
            if node.type == CompactNodeType.DECISION
        }

        for decision_id in decision_ids:
            outgoing_count = len(outgoing.get(decision_id, []))

            if outgoing_count < 2:
                errors.append(
                    f"La DECISION '{decision_id}' debe tener al menos 2 salidas."
                )

        return errors

    def _validate_fork_topology(
        self,
        diagram: CompactDiagram,
        incoming: dict[str, list[str]],
        outgoing: dict[str, list[str]],
    ) -> list[str]:
        errors: list[str] = []

        for node in diagram.nodes:
            if node.type != CompactNodeType.FORK:
                continue

            incoming_count = len(incoming.get(node.id, []))
            outgoing_count = len(outgoing.get(node.id, []))

            is_split_fork = incoming_count == 1 and outgoing_count >= 2
            is_join_fork = incoming_count >= 2 and outgoing_count == 1

            if is_split_fork or is_join_fork:
                continue

            errors.append(
                f"El nodo FORK '{node.id}' debe comportarse como fork "
                "o como join. Un fork debe tener 1 entrada y 2 o más salidas. "
                "Un join debe tener 2 o más entradas y 1 salida."
            )

        return errors

    def _validate_decision_previous_action_select(
        self,
        diagram: CompactDiagram,
        template_suggestions: list[TemplateSuggestion],
        incoming: dict[str, list[str]],
        nodes_by_id: dict[str, CompactNode],
        existing_templates_by_id: dict[str, ExistingTemplateContext],
    ) -> list[str]:
        errors: list[str] = []

        suggestions_by_node_id = {
            suggestion.node_id: suggestion
            for suggestion in template_suggestions
        }

        for node in diagram.nodes:
            if node.type != CompactNodeType.DECISION:
                continue

            previous_node_ids = incoming.get(node.id, [])
            previous_actions = [
                nodes_by_id[previous_id]
                for previous_id in previous_node_ids
                if previous_id in nodes_by_id
                and nodes_by_id[previous_id].type == CompactNodeType.ACTION
            ]

            if not previous_actions:
                errors.append(
                    f"La DECISION '{node.id}' debe tener un ACTION anterior."
                )
                continue

            if len(previous_actions) > 1:
                errors.append(
                    f"La DECISION '{node.id}' tiene más de un ACTION anterior. "
                    "Para esta versión debe tener uno solo."
                )
                continue

            previous_action = previous_actions[0]
            suggestion = suggestions_by_node_id.get(previous_action.id)

            if not suggestion:
                errors.append(
                    f"El ACTION anterior '{previous_action.id}' no tiene "
                    "template_suggestion."
                )
                continue

            decision_labels = self._get_decision_outgoing_labels(
                diagram=diagram,
                decision_id=node.id,
            )

            select_options = self._get_select_options_from_suggestion(
                suggestion=suggestion,
                existing_templates_by_id=existing_templates_by_id,
            )

            if not select_options:
                errors.append(
                    f"El ACTION anterior '{previous_action.id}' debe tener "
                    f"un campo SELECT compatible para la DECISION '{node.id}'."
                )
                continue

            missing_labels = decision_labels - select_options

            if missing_labels:
                errors.append(
                    f"La DECISION '{node.id}' tiene labels "
                    f"{sorted(decision_labels)}, pero el SELECT del ACTION "
                    f"'{previous_action.id}' solo tiene opciones "
                    f"{sorted(select_options)}."
                )

        return errors

    def _validate_action_select_has_decision_after(
        self,
        diagram: CompactDiagram,
        template_suggestions: list[TemplateSuggestion],
        outgoing: dict[str, list[str]],
        nodes_by_id: dict[str, CompactNode],
        existing_templates_by_id: dict[str, ExistingTemplateContext],
    ) -> list[str]:
        errors: list[str] = []

        suggestions_by_node_id = {
            suggestion.node_id: suggestion
            for suggestion in template_suggestions
        }

        for node in diagram.nodes:
            if node.type != CompactNodeType.ACTION:
                continue

            suggestion = suggestions_by_node_id.get(node.id)
            if not suggestion:
                continue

            if not self._has_decision_select(
                suggestion=suggestion,
                existing_templates_by_id=existing_templates_by_id,
            ):
                continue

            next_node_ids = outgoing.get(node.id, [])
            has_decision_after = any(
                next_id in nodes_by_id
                and nodes_by_id[next_id].type == CompactNodeType.DECISION
                for next_id in next_node_ids
            )

            if not has_decision_after:
                errors.append(
                    f"El ACTION '{node.id}' tiene un SELECT decisorio, "
                    "pero no tiene una DECISION inmediatamente después."
                )

        return errors

    def _validate_no_orphan_nodes(
        self,
        diagram: CompactDiagram,
        outgoing: dict[str, list[str]],
    ) -> list[str]:
        errors: list[str] = []

        initial_nodes = [
            node
            for node in diagram.nodes
            if node.type == CompactNodeType.INITIAL
        ]

        if not initial_nodes:
            return ["El diagrama no tiene nodo INITIAL."]

        initial_id = initial_nodes[0].id
        reachable = self._reachable_from(initial_id, outgoing)

        for node in diagram.nodes:
            if node.id not in reachable:
                errors.append(
                    f"El nodo '{node.id}' está huérfano: no es alcanzable "
                    "desde INITIAL."
                )

        return errors

    def _validate_every_action_reaches_final(
        self,
        diagram: CompactDiagram,
        outgoing: dict[str, list[str]],
    ) -> list[str]:
        errors: list[str] = []

        final_ids = {
            node.id
            for node in diagram.nodes
            if node.type == CompactNodeType.FINAL
        }

        if not final_ids:
            return ["El diagrama no tiene nodo FINAL."]

        for node in diagram.nodes:
            if node.type != CompactNodeType.ACTION:
                continue

            reachable = self._reachable_from(node.id, outgoing)

            if not reachable.intersection(final_ids):
                errors.append(
                    f"El ACTION '{node.id}' no tiene ruta hacia ningún FINAL."
                )

        return errors

    def _reachable_from(
        self,
        start_id: str,
        outgoing: dict[str, list[str]],
    ) -> set[str]:
        visited: set[str] = set()
        queue: deque[str] = deque([start_id])

        while queue:
            current = queue.popleft()

            if current in visited:
                continue

            visited.add(current)

            for next_id in outgoing.get(current, []):
                if next_id not in visited:
                    queue.append(next_id)

        return visited

    def _get_decision_outgoing_labels(
        self,
        diagram: CompactDiagram,
        decision_id: str,
    ) -> set[str]:
        labels: set[str] = set()

        for link in diagram.links:
            if link.source_id != decision_id:
                continue

            if link.label:
                labels.add(self._normalize_value(link.label))

        return labels

    def _get_select_options_from_suggestion(
        self,
        suggestion: TemplateSuggestion,
        existing_templates_by_id: dict[str, ExistingTemplateContext],
    ) -> set[str]:
        if suggestion.strategy == TemplateStrategy.USE_EXISTING_TEMPLATE:
            if not suggestion.existing_template_id:
                return set()

            existing_template = existing_templates_by_id.get(
                suggestion.existing_template_id,
            )

            if not existing_template:
                return set()

            return self._get_select_options_from_existing_template(
                existing_template,
            )

        if not suggestion.template:
            return set()

        options: set[str] = set()

        for field in suggestion.template.fields:
            if field.type != FieldType.SELECT:
                continue

            for option in field.options:
                options.add(self._normalize_value(option.label))
                options.add(self._normalize_value(option.value))

        return options

    def _get_select_options_from_existing_template(
        self,
        template: ExistingTemplateContext,
    ) -> set[str]:
        options: set[str] = set()

        for field in template.fields:
            if field.type != FieldType.SELECT:
                continue

            for option in field.options:
                options.add(self._normalize_value(option.label))
                options.add(self._normalize_value(option.value))

        return options

    def _has_decision_select(
        self,
        suggestion: TemplateSuggestion,
        existing_templates_by_id: dict[str, ExistingTemplateContext],
    ) -> bool:
        option_values = self._get_select_options_from_suggestion(
            suggestion=suggestion,
            existing_templates_by_id=existing_templates_by_id,
        )

        if not option_values:
            return False

        if {"si", "no"}.issubset(option_values):
            return True

        if {"aprobado", "rechazado"}.issubset(option_values):
            return True

        if {"aceptado", "rechazado"}.issubset(option_values):
            return True

        if {"disponible", "no disponible"}.issubset(option_values):
            return True

        return False

    def _normalize_value(self, value: str) -> str:
        normalized = value.strip().lower()
        normalized = normalized.replace("sí", "si")
        normalized = normalized.replace("á", "a")
        normalized = normalized.replace("é", "e")
        normalized = normalized.replace("í", "i")
        normalized = normalized.replace("ó", "o")
        normalized = normalized.replace("ú", "u")
        return normalized
