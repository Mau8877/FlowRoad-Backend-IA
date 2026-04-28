from typing import Any

from app.schemas.diagram_ai_schemas import DiagramAiRequest
from app.services.repairers.decision_repairer import DecisionRepairer
from app.services.repairers.final_node_repairer import FinalNodeRepairer
from app.services.repairers.fork_join_repairer import ForkJoinRepairer
from app.services.repairers.link_repairer import LinkRepairer
from app.services.repairers.template_repairer import TemplateRepairer


class DiagramAiAutoRepairer:
    def __init__(self) -> None:
        self.decision_repairer = DecisionRepairer()
        self.final_node_repairer = FinalNodeRepairer()
        self.fork_join_repairer = ForkJoinRepairer()
        self.link_repairer = LinkRepairer()
        self.template_repairer = TemplateRepairer()

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

        self.template_repairer.reuse_existing_templates_by_name(
            suggestions=suggestions,
            request=request,
            changes=changes,
        )

        self.final_node_repairer.ensure_final_node_exists(
            nodes=nodes,
            changes=changes,
        )

        self.decision_repairer.ensure_decisions_have_action_before(
            nodes=nodes,
            links=links,
            changes=changes,
        )

        self.decision_repairer.create_missing_decisions_after_decisive_actions(
            nodes=nodes,
            links=links,
            suggestions=suggestions,
            request=request,
            changes=changes,
        )

        self.decision_repairer.ensure_decisions_have_two_outputs(
            nodes=nodes,
            links=links,
            suggestions=suggestions,
            request=request,
            changes=changes,
        )

        self.decision_repairer.ensure_previous_actions_have_compatible_select(
            nodes=nodes,
            links=links,
            suggestions=suggestions,
            request=request,
            changes=changes,
        )

        self.fork_join_repairer.repair_parallel_empty_branch_links(
            nodes=nodes,
            links=links,
            changes=changes,
        )

        self.link_repairer.ensure_actions_reach_final(
            nodes=nodes,
            links=links,
            changes=changes,
        )

        self.link_repairer.ensure_unique_link_ids(
            links=links,
            changes=changes,
        )

        return parsed_response