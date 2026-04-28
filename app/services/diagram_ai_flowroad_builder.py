from typing import Any

from fastapi import HTTPException, status

from app.schemas.diagram_ai_schemas import (
    CompactNode,
    CompactNodeType,
    DiagramAiCompactResponse,
    DiagramAiRequest,
    DiagramAiResponse,
    FlowRoadDiagram,
    TemplateStrategy,
    TemplateSuggestion,
)


class DiagramAiFlowRoadBuilder:
    def build_flowroad_response(
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

        self.normalize_invalid_departments(
            nodes=compact_response.diagram.nodes,
            departments_by_id=departments_by_id,
            warnings=warnings,
        )

        valid_template_suggestions = self.filter_template_suggestions_for_actions(
            nodes=compact_response.diagram.nodes,
            template_suggestions=compact_response.template_suggestions,
            warnings=warnings,
        )

        template_by_node_id = {
            suggestion.node_id: suggestion
            for suggestion in valid_template_suggestions
        }

        lanes = self.build_lanes(
            nodes=compact_response.diagram.nodes,
            departments_by_id=departments_by_id,
        )

        cells: list[dict[str, Any]] = []

        cells.extend(
            self.build_node_cells(
                nodes=compact_response.diagram.nodes,
                lanes=lanes,
                template_by_node_id=template_by_node_id,
            )
        )

        cells.extend(
            self.build_link_cells(
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
            template_suggestions=valid_template_suggestions,
            warnings=warnings,
            changes_summary=compact_response.changes_summary,
        )

    def normalize_invalid_departments(
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

    def filter_template_suggestions_for_actions(
        self,
        nodes: list[CompactNode],
        template_suggestions: list[TemplateSuggestion],
        warnings: list[str],
    ) -> list[TemplateSuggestion]:
        action_ids = {
            node.id
            for node in nodes
            if node.type == CompactNodeType.ACTION
        }

        valid_suggestions: list[TemplateSuggestion] = []

        for suggestion in template_suggestions:
            if suggestion.node_id in action_ids:
                valid_suggestions.append(suggestion)
                continue

            warnings.append(
                "Se ignoró una template_suggestion asociada a un nodo que "
                f"no es ACTION: {suggestion.node_id}."
            )

        return valid_suggestions

    def build_lanes(
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

    def build_node_cells(
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
                cells.append(self.build_initial_node(node, lane, position_y))
                continue

            if node.type == CompactNodeType.FINAL:
                cells.append(self.build_final_node(node, lane, position_y))
                continue

            if node.type == CompactNodeType.DECISION:
                cells.append(self.build_decision_node(node, lane, position_y))
                continue

            if node.type == CompactNodeType.FORK:
                cells.append(self.build_fork_node(node, lane, position_y))
                continue

            template_suggestion = template_by_node_id.get(node.id)

            cells.append(
                self.build_action_node(
                    node=node,
                    lane=lane,
                    position_y=position_y,
                    template_suggestion=template_suggestion,
                )
            )

        return cells

    def build_initial_node(
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

    def build_final_node(
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

    def build_action_node(
        self,
        node: CompactNode,
        lane: dict[str, Any],
        position_y: int,
        template_suggestion: Any,
    ) -> dict[str, Any]:
        template_document_id = ""

        if (
            template_suggestion
            and template_suggestion.strategy == TemplateStrategy.USE_EXISTING_TEMPLATE
        ):
            template_document_id = template_suggestion.existing_template_id or ""

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
                "label": self.build_node_label_attrs(node.name),
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

    def build_decision_node(
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

    def build_fork_node(
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
                "nombre": node.name or "Fork/Join",
                "tipo": "FORK",
                "laneId": lane["id"],
            },
            "labels": None,
            "vertices": None,
            "router": None,
            "connector": None,
        }

    def build_link_cells(
        self,
        links: list[Any],
        nodes: list[CompactNode],
    ) -> list[dict[str, Any]]:
        node_by_id = {
            node.id: node
            for node in nodes
        }

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
                        "line": self.build_link_line_attrs(),
                    },
                    "customData": custom_data,
                    "labels": self.build_link_labels(
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

    def build_node_label_attrs(self, text: str) -> dict[str, Any]:
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

    def build_link_line_attrs(self) -> dict[str, Any]:
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

    def build_link_labels(
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