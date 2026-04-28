from typing import Any
from app.schemas.diagram_ai_schemas import DiagramAiRequest


class BaseRepairer:
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
