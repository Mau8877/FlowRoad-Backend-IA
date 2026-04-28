import json
import re
from datetime import date
from typing import Any

from fastapi import HTTPException, status
from pydantic import ValidationError

from app.core.worker_ai_prompt import WORKER_AI_SYSTEM_PROMPT
from app.schemas.worker_ai_schemas import (WorkerAiRequest, WorkerAiResponse,
                                           WorkerFieldSuggestion,
                                           WorkerFieldType,
                                           WorkerTemplateField)
from app.services.diagram_ai_error_serializer import DiagramAiErrorSerializer
from app.services.diagram_ai_response_parser import DiagramAiResponseParser
from app.services.openrouter_service import OpenRouterService


class WorkerAiService:
    MODEL_TEMPERATURE = 0.1
    MODEL_MAX_TOKENS = 2500

    def __init__(self) -> None:
        self.openrouter_service = OpenRouterService()
        self.response_parser = DiagramAiResponseParser()
        self.error_serializer = DiagramAiErrorSerializer()

    async def assist_template(
        self,
        request: WorkerAiRequest,
    ) -> WorkerAiResponse:
        raw_response = await self._call_model(request)

        parsed_response = self.response_parser.parse_json_response(
            raw_response,
        )

        repaired_response = self._repair_response(
            parsed_response=parsed_response,
            request=request,
        )

        try:
            return WorkerAiResponse.model_validate(repaired_response)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "message": (
                        "La IA devolvió JSON, pero no cumple el formato "
                        "esperado para asistencia de worker."
                    ),
                    "errors": self.error_serializer.serialize_validation_errors(
                        exc,
                    ),
                    "raw_response": raw_response,
                    "cleaned_response": repaired_response,
                },
            ) from exc

    async def _call_model(self, request: WorkerAiRequest) -> str:
        user_prompt = self._build_user_prompt(request)

        return await self.openrouter_service.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": WORKER_AI_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            temperature=self.MODEL_TEMPERATURE,
            max_tokens=self.MODEL_MAX_TOKENS,
        )

    def _build_user_prompt(self, request: WorkerAiRequest) -> str:
        payload = {
            "worker_message": request.worker_message,
            "task_name": request.task_name,
            "process_name": request.process_name,
            "worker_name": request.worker_name,
            "department_name": request.department_name,
            "target_field_id": request.target_field_id,
            "current_date": date.today().isoformat(),
            "template": request.template.model_dump(mode="json"),
            "current_values": request.current_values,
            "extra_context": request.extra_context,
        }

        return (
            "Genera sugerencias para completar la plantilla del worker.\n"
            "Si target_field_id tiene valor, responde solo ese campo.\n"
            "Si target_field_id es null, responde todos los campos.\n\n"
            "Datos recibidos:\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )

    def _repair_response(
        self,
        parsed_response: dict[str, Any],
        request: WorkerAiRequest,
    ) -> dict[str, Any]:
        if not isinstance(parsed_response, dict):
            parsed_response = {}

        message = str(
            parsed_response.get("message")
            or "Sugerencia generada correctamente."
        )

        raw_suggestions = parsed_response.get("field_suggestions")

        if not isinstance(raw_suggestions, list):
            raw_suggestions = []

        raw_warnings = parsed_response.get("warnings")

        if not isinstance(raw_warnings, list):
            raw_warnings = []

        warnings = [
            str(warning) for warning in raw_warnings if str(warning).strip()
        ]

        suggestions_by_field_id = self._build_suggestions_by_field_id(
            raw_suggestions,
        )

        fields = self._resolve_target_fields(request)
        repaired_suggestions: list[dict[str, Any]] = []

        for field in fields:
            raw_suggestion = suggestions_by_field_id.get(field.field_id, {})

            suggestion = self._repair_field_suggestion(
                field=field,
                raw_suggestion=raw_suggestion,
                request=request,
            )

            if suggestion.warning:
                warnings.append(suggestion.warning)

            repaired_suggestions.append(
                suggestion.model_dump(mode="json"),
            )

        return {
            "message": message,
            "field_suggestions": repaired_suggestions,
            "warnings": self._unique_values(warnings),
        }

    def _resolve_target_fields(
        self,
        request: WorkerAiRequest,
    ) -> list[WorkerTemplateField]:
        if not request.target_field_id:
            return request.template.fields

        return [
            field
            for field in request.template.fields
            if field.field_id == request.target_field_id
        ]

    def _build_suggestions_by_field_id(
        self,
        raw_suggestions: list[Any],
    ) -> dict[str, dict[str, Any]]:
        suggestions_by_field_id: dict[str, dict[str, Any]] = {}

        for item in raw_suggestions:
            if not isinstance(item, dict):
                continue

            field_id = str(
                item.get("field_id") or item.get("fieldId") or "",
            ).strip()

            if not field_id:
                continue

            suggestions_by_field_id[field_id] = item

        return suggestions_by_field_id

    def _repair_field_suggestion(
        self,
        field: WorkerTemplateField,
        raw_suggestion: dict[str, Any],
        request: WorkerAiRequest,
    ) -> WorkerFieldSuggestion:
        raw_value = self._extract_raw_value(
            field=field,
            raw_suggestion=raw_suggestion,
            request=request,
        )

        suggested_value, warning = self._coerce_value(
            field=field,
            raw_value=raw_value,
            request=request,
        )

        raw_warning = raw_suggestion.get("warning")
        if raw_warning and not warning:
            warning = str(raw_warning)

        if field.required and self._is_empty_value(suggested_value):
            warning = (
                warning
                or f"El campo '{field.label}' es obligatorio y no tiene "
                "una sugerencia clara."
            )

        confidence = self._coerce_confidence(
            raw_suggestion.get("confidence"),
        )

        if field.type in {WorkerFieldType.FILE, WorkerFieldType.PHOTO}:
            confidence = 0.0

        if self._is_empty_value(suggested_value):
            confidence = min(confidence, 0.35)

        return WorkerFieldSuggestion(
            field_id=field.field_id,
            label=field.label,
            type=field.type,
            suggested_value=suggested_value,
            confidence=confidence,
            warning=warning,
        )

    def _extract_raw_value(
        self,
        field: WorkerTemplateField,
        raw_suggestion: dict[str, Any],
        request: WorkerAiRequest,
    ) -> Any:
        if "suggested_value" in raw_suggestion:
            return raw_suggestion.get("suggested_value")

        if "suggestedValue" in raw_suggestion:
            return raw_suggestion.get("suggestedValue")

        if field.field_id in request.current_values:
            return request.current_values.get(field.field_id)

        return None

    def _coerce_confidence(self, value: Any) -> float:
        if isinstance(value, bool):
            return 0.7

        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))

        return 0.7

    def _coerce_value(
        self,
        field: WorkerTemplateField,
        raw_value: Any,
        request: WorkerAiRequest,
    ) -> tuple[Any, str | None]:
        if field.type == WorkerFieldType.TEXT:
            return self._coerce_text(
                raw_value=raw_value,
                fallback=request.worker_message,
                max_length=140,
            )

        if field.type == WorkerFieldType.TEXTAREA:
            return self._coerce_textarea(
                raw_value=raw_value,
                fallback=request.worker_message,
            )

        if field.type == WorkerFieldType.NUMBER:
            return self._coerce_number(raw_value)

        if field.type == WorkerFieldType.SELECT:
            return self._coerce_select(
                field=field,
                raw_value=raw_value,
            )

        if field.type == WorkerFieldType.MULTIPLE_CHOICE:
            return self._coerce_multiple_choice(
                field=field,
                raw_value=raw_value,
            )

        if field.type == WorkerFieldType.DATE:
            return self._coerce_date(raw_value)

        if field.type == WorkerFieldType.FILE:
            return (
                None,
                f"El campo '{field.label}' requiere adjuntar un archivo "
                "manualmente.",
            )

        if field.type == WorkerFieldType.PHOTO:
            return (
                None,
                f"El campo '{field.label}' requiere adjuntar una foto "
                "manualmente.",
            )

        return None, f"No se pudo sugerir valor para '{field.label}'."

    def _coerce_text(
        self,
        raw_value: Any,
        fallback: str,
        max_length: int,
    ) -> tuple[str | None, str | None]:
        value = str(raw_value or "").strip()

        if not value:
            value = fallback.strip()

        if not value:
            return None, "No se detectó texto suficiente para este campo."

        if len(value) > max_length:
            value = value[:max_length].rstrip()

        return value, None

    def _coerce_textarea(
        self,
        raw_value: Any,
        fallback: str,
    ) -> tuple[str | None, str | None]:
        value = str(raw_value or "").strip()

        if not value:
            value = fallback.strip()

        if not value:
            return None, "No se detectó texto suficiente para este campo."

        return value, None

    def _coerce_number(
        self,
        raw_value: Any,
    ) -> tuple[int | float | None, str | None]:
        if isinstance(raw_value, bool):
            return None, "No se detectó un número válido."

        if isinstance(raw_value, (int, float)):
            return raw_value, None

        text = str(raw_value or "").strip()

        if not text:
            return None, "No se detectó un número claro para este campo."

        match = re.search(r"-?\d+(?:[.,]\d+)?", text)

        if not match:
            return None, "No se detectó un número claro para este campo."

        number_text = match.group(0).replace(",", ".")

        try:
            number = float(number_text)
        except ValueError:
            return None, "No se pudo convertir el valor detectado a número."

        if number.is_integer():
            return int(number), None

        return number, None

    def _coerce_select(
        self,
        field: WorkerTemplateField,
        raw_value: Any,
    ) -> tuple[str | None, str | None]:
        option_map = self._build_option_map(field)
        normalized_value = self._normalize_text(str(raw_value or ""))

        if not normalized_value:
            return (
                None,
                f"No se detectó una opción clara para '{field.label}'.",
            )

        selected_value = option_map.get(normalized_value)

        if selected_value:
            return selected_value, None

        return (
            None,
            f"El valor sugerido para '{field.label}' no coincide con las "
            "opciones disponibles.",
        )

    def _coerce_multiple_choice(
        self,
        field: WorkerTemplateField,
        raw_value: Any,
    ) -> tuple[list[str], str | None]:
        option_map = self._build_option_map(field)

        if isinstance(raw_value, list):
            raw_items = raw_value
        else:
            raw_items = re.split(r"[,;/|]", str(raw_value or ""))

        selected_values: list[str] = []

        for item in raw_items:
            normalized_item = self._normalize_text(str(item))
            selected_value = option_map.get(normalized_item)

            if selected_value and selected_value not in selected_values:
                selected_values.append(selected_value)

        if selected_values:
            return selected_values, None

        return [], f"No se detectaron opciones claras para '{field.label}'."

    def _coerce_date(
        self,
        raw_value: Any,
    ) -> tuple[str | None, str | None]:
        text = str(raw_value or "").strip()

        if not text:
            return None, "No se detectó una fecha clara para este campo."

        match = re.search(r"\d{4}-\d{2}-\d{2}", text)

        if not match:
            return None, "La fecha sugerida no tiene formato YYYY-MM-DD."

        return match.group(0), None

    def _build_option_map(
        self,
        field: WorkerTemplateField,
    ) -> dict[str, str]:
        option_map: dict[str, str] = {}

        for option in field.options:
            normalized_label = self._normalize_text(option.label)
            normalized_value = self._normalize_text(option.value)

            option_map[normalized_label] = option.value
            option_map[normalized_value] = option.value

        return option_map

    def _is_empty_value(self, value: Any) -> bool:
        if value is None:
            return True

        if isinstance(value, str):
            return not value.strip()

        if isinstance(value, list | tuple | set | dict):
            return len(value) == 0

        return False

    def _unique_values(self, values: list[str]) -> list[str]:
        result: list[str] = []
        used: set[str] = set()

        for value in values:
            normalized = self._normalize_text(value)

            if not normalized or normalized in used:
                continue

            result.append(value)
            used.add(normalized)

        return result

    def _normalize_text(self, value: str) -> str:
        normalized = value.strip().lower()
        normalized = normalized.replace("sí", "si")
        normalized = normalized.replace("á", "a")
        normalized = normalized.replace("é", "e")
        normalized = normalized.replace("í", "i")
        normalized = normalized.replace("ó", "o")
        normalized = normalized.replace("ú", "u")
        normalized = normalized.replace("ñ", "n")
        normalized = " ".join(normalized.split())
        return normalized
