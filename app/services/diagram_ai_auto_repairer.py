from typing import Any

from app.schemas.diagram_ai_schemas import DiagramAiRequest


class DiagramAiAutoRepairer:
    def repair(
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

        self._reuse_existing_templates_by_name(
            suggestions=suggestions,
            request=request,
            changes=changes,
        )

        self._ensure_final_node_exists(
            nodes=nodes,
            changes=changes,
        )

        self._ensure_decisions_have_action_before(
            nodes=nodes,
            links=links,
            changes=changes,
        )

        self._create_missing_decisions_after_decisive_actions(
            nodes=nodes,
            links=links,
            suggestions=suggestions,
            request=request,
            changes=changes,
        )

        self._ensure_decisions_have_two_outputs(
            nodes=nodes,
            links=links,
            suggestions=suggestions,
            request=request,
            changes=changes,
        )

        self._ensure_previous_actions_have_compatible_select(
            nodes=nodes,
            links=links,
            suggestions=suggestions,
            request=request,
            changes=changes,
        )

        self._repair_parallel_empty_branch_links(
            nodes=nodes,
            links=links,
            changes=changes,
        )

        self._ensure_actions_reach_final(
            nodes=nodes,
            links=links,
            changes=changes,
        )

        self._ensure_unique_link_ids(
            links=links,
            changes=changes,
        )

        return parsed_response

    def _ensure_final_node_exists(
        self,
        nodes: list[dict[str, Any]],
        changes: list[str],
    ) -> None:
        has_final = any(
            isinstance(node, dict) and node.get("type") == "FINAL"
            for node in nodes
        )

        if has_final:
            return

        department_id = self._resolve_department_id_for_auto_final(nodes)

        nodes.append(
            {
                "id": "node-final",
                "type": "FINAL",
                "name": "Fin",
                "department_id": department_id,
            }
        )

        changes.append(
            "Se creó automáticamente un nodo FINAL porque la IA no lo incluyó."
        )

    def _resolve_department_id_for_auto_final(
        self,
        nodes: list[dict[str, Any]],
    ) -> str:
        for node in reversed(nodes):
            if not isinstance(node, dict):
                continue

            department_id = str(node.get("department_id") or "").strip()

            if department_id:
                return department_id

        return ""

    def _reuse_existing_templates_by_name(
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

    def _ensure_decisions_have_action_before(
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

    def _create_missing_decisions_after_decisive_actions(
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

    def _ensure_decisions_have_two_outputs(
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

    def _ensure_previous_actions_have_compatible_select(
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

    def _repair_parallel_empty_branch_links(
        self,
        nodes: list[dict[str, Any]],
        links: list[dict[str, Any]],
        changes: list[str],
    ) -> None:
        node_by_id = self._build_node_by_id(nodes)

        self._repair_duplicate_fork_outputs_to_action(
            links=links,
            node_by_id=node_by_id,
            changes=changes,
        )

        node_by_id = self._build_node_by_id(nodes)

        self._repair_single_remaining_parallel_branch(
            links=links,
            node_by_id=node_by_id,
            changes=changes,
        )

        node_by_id = self._build_node_by_id(nodes)

        self._collapse_empty_fork_join_pairs(
            nodes=nodes,
            links=links,
            node_by_id=node_by_id,
            changes=changes,
        )

    def _repair_duplicate_fork_outputs_to_action(
        self,
        links: list[dict[str, Any]],
        node_by_id: dict[str, dict[str, Any]],
        changes: list[str],
    ) -> None:
        fork_ids = {
            node_id
            for node_id, node in node_by_id.items()
            if node.get("type") == "FORK"
        }

        for fork_id in fork_ids:
            outgoing_links = self._get_outgoing_links(links, fork_id)
            links_by_target: dict[str, list[dict[str, Any]]] = {}

            for link in outgoing_links:
                target_id = str(link.get("target_id") or "")
                if not target_id:
                    continue

                links_by_target.setdefault(target_id, []).append(link)

            for target_id, duplicated_links in links_by_target.items():
                if len(duplicated_links) < 2:
                    continue

                target_node = node_by_id.get(target_id)
                if not target_node or target_node.get("type") != "ACTION":
                    continue

                join_id = self._find_direct_fork_target_from_action(
                    action_id=target_id,
                    links=links,
                    node_by_id=node_by_id,
                    excluded_fork_id=fork_id,
                )

                if not join_id:
                    continue

                if self._has_link(links, fork_id, join_id):
                    self._remove_extra_duplicated_links(
                        links=links,
                        duplicated_links=duplicated_links,
                        keep_count=1,
                    )
                    changes.append(
                        f"Se eliminaron links duplicados desde FORK '{fork_id}' "
                        f"hacia ACTION '{target_id}'."
                    )
                    continue

                link_to_repair = duplicated_links[1]
                link_to_repair["target_id"] = join_id
                link_to_repair["label"] = None
                link_to_repair["id"] = self._build_link_id(fork_id, join_id)

                changes.append(
                    f"Se reparó una rama paralela vacía creando conexión "
                    f"directa desde FORK '{fork_id}' hacia FORK '{join_id}'."
                )

    def _repair_single_remaining_parallel_branch(
        self,
        links: list[dict[str, Any]],
        node_by_id: dict[str, dict[str, Any]],
        changes: list[str],
    ) -> None:
        for fork_id, fork_node in node_by_id.items():
            if fork_node.get("type") != "FORK":
                continue

            incoming_links = self._get_incoming_links(links, fork_id)
            outgoing_links = self._get_outgoing_links(links, fork_id)

            if len(incoming_links) != 1:
                continue

            if len(outgoing_links) != 1:
                continue

            only_target_id = str(outgoing_links[0].get("target_id") or "")
            only_target_node = node_by_id.get(only_target_id)

            if not only_target_node or only_target_node.get("type") != "ACTION":
                continue

            join_id = self._find_direct_fork_target_from_action(
                action_id=only_target_id,
                links=links,
                node_by_id=node_by_id,
                excluded_fork_id=fork_id,
            )

            if not join_id:
                continue

            join_incoming_links = self._get_incoming_links(links, join_id)
            join_outgoing_links = self._get_outgoing_links(links, join_id)

            if len(join_incoming_links) != 1:
                continue

            if len(join_outgoing_links) != 1:
                continue

            if self._has_link(links, fork_id, join_id):
                continue

            links.append(
                {
                    "id": self._build_link_id(fork_id, join_id),
                    "source_id": fork_id,
                    "target_id": join_id,
                    "label": None,
                }
            )

            changes.append(
                f"Se agregó un link directo desde FORK '{fork_id}' hacia "
                f"FORK '{join_id}' para representar una rama paralela vacía."
            )

    def _collapse_empty_fork_join_pairs(
        self,
        nodes: list[dict[str, Any]],
        links: list[dict[str, Any]],
        node_by_id: dict[str, dict[str, Any]],
        changes: list[str],
    ) -> None:
        changed = True

        while changed:
            changed = False
            node_by_id = self._build_node_by_id(nodes)

            for fork_id, fork_node in list(node_by_id.items()):
                if fork_node.get("type") != "FORK":
                    continue

                incoming_to_fork = self._get_incoming_links(links, fork_id)
                outgoing_from_fork = self._get_outgoing_links(links, fork_id)

                if len(incoming_to_fork) != 1:
                    continue

                if len(outgoing_from_fork) != 1:
                    continue

                previous_id = str(incoming_to_fork[0].get("source_id") or "")
                possible_join_id = str(outgoing_from_fork[0].get("target_id") or "")

                if not previous_id or not possible_join_id:
                    continue

                possible_join = node_by_id.get(possible_join_id)

                if not possible_join or possible_join.get("type") != "FORK":
                    continue

                incoming_to_join = self._get_incoming_links(links, possible_join_id)
                outgoing_from_join = self._get_outgoing_links(links, possible_join_id)

                if len(incoming_to_join) != 1:
                    continue

                if len(outgoing_from_join) != 1:
                    continue

                if incoming_to_join[0].get("source_id") != fork_id:
                    continue

                next_id = str(outgoing_from_join[0].get("target_id") or "")

                if not next_id:
                    continue

                previous_node = node_by_id.get(previous_id)
                next_node = node_by_id.get(next_id)

                if not previous_node or not next_node:
                    continue

                if previous_node.get("type") == "FORK":
                    continue

                if next_node.get("type") == "FORK":
                    continue

                links[:] = [
                    link
                    for link in links
                    if not (
                        isinstance(link, dict)
                        and (
                            link.get("source_id") in {fork_id, possible_join_id}
                            or link.get("target_id") in {fork_id, possible_join_id}
                        )
                    )
                ]

                nodes[:] = [
                    node
                    for node in nodes
                    if not (
                        isinstance(node, dict)
                        and node.get("id") in {fork_id, possible_join_id}
                    )
                ]

                if not self._has_link(links, previous_id, next_id):
                    links.append(
                        {
                            "id": self._build_link_id(previous_id, next_id),
                            "source_id": previous_id,
                            "target_id": next_id,
                            "label": None,
                        }
                    )

                changes.append(
                    f"Se eliminaron los FORK '{fork_id}' y '{possible_join_id}' "
                    f"porque ya no existían ramas paralelas. Se conectó "
                    f"'{previous_id}' directamente con '{next_id}'."
                )

                changed = True
                break

    def _find_direct_fork_target_from_action(
        self,
        action_id: str,
        links: list[dict[str, Any]],
        node_by_id: dict[str, dict[str, Any]],
        excluded_fork_id: str,
    ) -> str | None:
        for link in self._get_outgoing_links(links, action_id):
            target_id = str(link.get("target_id") or "")

            if not target_id:
                continue

            if target_id == excluded_fork_id:
                continue

            target_node = node_by_id.get(target_id)

            if not target_node:
                continue

            if target_node.get("type") == "FORK":
                return target_id

        return None

    def _remove_extra_duplicated_links(
        self,
        links: list[dict[str, Any]],
        duplicated_links: list[dict[str, Any]],
        keep_count: int,
    ) -> None:
        duplicated_object_ids = {
            id(link)
            for link in duplicated_links[keep_count:]
        }

        links[:] = [
            link
            for link in links
            if id(link) not in duplicated_object_ids
        ]

    def _ensure_actions_reach_final(
        self,
        nodes: list[dict[str, Any]],
        links: list[dict[str, Any]],
        changes: list[str],
    ) -> None:
        final_id = self._get_first_final_id(nodes)
        if not final_id:
            return

        outgoing_map = self._build_outgoing_map(links)

        for node in nodes:
            if not isinstance(node, dict):
                continue

            if node.get("type") != "ACTION":
                continue

            node_id = str(node.get("id") or "")
            if not node_id:
                continue

            reachable = self._reachable_from(node_id, outgoing_map)

            if final_id in reachable:
                continue

            links.append(
                {
                    "id": self._build_link_id(node_id, final_id),
                    "source_id": node_id,
                    "target_id": final_id,
                    "label": None,
                }
            )

            outgoing_map.setdefault(node_id, []).append(final_id)

            changes.append(
                f"Se conectó automáticamente el ACTION '{node_id}' al FINAL."
            )

    def _ensure_unique_link_ids(
        self,
        links: list[dict[str, Any]],
        changes: list[str],
    ) -> None:
        used_ids: set[str] = set()
        renamed_count = 0

        for index, link in enumerate(links):
            if not isinstance(link, dict):
                continue

            current_id = str(link.get("id") or "").strip()

            source_id = str(link.get("source_id") or f"source-{index}")
            target_id = str(link.get("target_id") or f"target-{index}")
            label = str(link.get("label") or "")

            if not current_id:
                current_id = self._build_link_id(
                    source_id=source_id,
                    target_id=target_id,
                    label=label or None,
                )

            candidate_id = current_id
            counter = 2

            while candidate_id in used_ids:
                candidate_id = f"{current_id}-{counter}"
                counter += 1

            if candidate_id != link.get("id"):
                link["id"] = candidate_id
                renamed_count += 1

            used_ids.add(candidate_id)

        if renamed_count:
            changes.append(
                f"Se corrigieron {renamed_count} IDs duplicados de links."
            )

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

    def _build_node_by_id(
        self,
        nodes: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        return {
            str(node.get("id")): node
            for node in nodes
            if isinstance(node, dict) and node.get("id")
        }

    def _get_outgoing_links(
        self,
        links: list[dict[str, Any]],
        node_id: str,
    ) -> list[dict[str, Any]]:
        return [
            link
            for link in links
            if isinstance(link, dict)
            and link.get("source_id") == node_id
        ]

    def _get_incoming_links(
        self,
        links: list[dict[str, Any]],
        node_id: str,
    ) -> list[dict[str, Any]]:
        return [
            link
            for link in links
            if isinstance(link, dict)
            and link.get("target_id") == node_id
        ]

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

    def _get_first_final_id(
        self,
        nodes: list[dict[str, Any]],
    ) -> str | None:
        for node in nodes:
            if not isinstance(node, dict):
                continue

            if node.get("type") != "FINAL":
                continue

            node_id = node.get("id")
            return str(node_id) if node_id else None

        return None

    def _build_outgoing_map(
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

    def _has_link(
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

    def _build_link_id(
        self,
        source_id: str,
        target_id: str,
        label: str | None = None,
    ) -> str:
        raw = f"link-{source_id}-{target_id}"

        if label:
            raw = f"{raw}-{label}"

        return self._slugify(raw)[:90]

    def _slugify(self, value: str) -> str:
        normalized = self._normalize_text(value)
        normalized = normalized.replace("/", " ")
        normalized = normalized.replace("_", " ")

        parts = [
            part
            for part in normalized.split()
            if part
        ]

        return "-".join(parts) or "item"

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