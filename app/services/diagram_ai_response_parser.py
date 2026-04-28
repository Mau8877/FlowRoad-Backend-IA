import json
import re
from typing import Any

from fastapi import HTTPException, status


class DiagramAiResponseParser:
    def parse_json_response(self, raw_response: str) -> dict[str, Any]:
        cleaned_response = self.clean_json_response(raw_response)

        try:
            parsed = json.loads(cleaned_response)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "message": "La IA no devolvió JSON válido.",
                    "error": str(exc),
                    "raw_response": raw_response,
                    "cleaned_response": cleaned_response,
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

    def clean_json_response(self, raw_response: str) -> str:
        cleaned = raw_response.strip()

        # Caso 1: la IA devuelve ```json ... ```
        fenced_match = re.search(
            r"```(?:json)?\s*(.*?)\s*```",
            cleaned,
            re.DOTALL | re.IGNORECASE,
        )

        if fenced_match:
            cleaned = fenced_match.group(1).strip()

        # Caso 2: la IA devuelve texto antes o después del JSON
        start = cleaned.find("{")
        end = cleaned.rfind("}")

        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start : end + 1].strip()

        return cleaned