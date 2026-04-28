from typing import Any
from app.services.repairers.base_repairer import BaseRepairer


class LinkRepairer(BaseRepairer):
    def ensure_actions_reach_final(
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

    def ensure_unique_link_ids(
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
