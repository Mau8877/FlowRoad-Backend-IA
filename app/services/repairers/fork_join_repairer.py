from typing import Any
from app.services.repairers.base_repairer import BaseRepairer


class ForkJoinRepairer(BaseRepairer):
    def repair_parallel_empty_branch_links(
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
