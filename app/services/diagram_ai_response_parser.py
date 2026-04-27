import json
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
                    "raw_response": raw_response,
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

        if cleaned.startswith("```json"):
            cleaned = cleaned.removeprefix("```json").strip()

        if cleaned.startswith("```"):
            cleaned = cleaned.removeprefix("```").strip()

        if cleaned.endswith("```"):
            cleaned = cleaned.removesuffix("```").strip()

        return cleaned