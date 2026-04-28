from typing import Any
from app.services.repairers.base_repairer import BaseRepairer


class FinalNodeRepairer(BaseRepairer):
    def ensure_final_node_exists(
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
