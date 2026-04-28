from fastapi import HTTPException, status
from pydantic import ValidationError

from app.schemas.diagram_ai_schemas import (
    DiagramAiCompactResponse,
    DiagramAiRawResponse,
    DiagramAiRequest,
    DiagramAiResponse,
)
from app.services.diagram_ai_auto_repairer import DiagramAiAutoRepairer
from app.services.diagram_ai_error_serializer import DiagramAiErrorSerializer
from app.services.diagram_ai_flowroad_builder import DiagramAiFlowRoadBuilder
from app.services.diagram_ai_prompt_builder import DiagramAiPromptBuilder
from app.services.diagram_ai_response_parser import DiagramAiResponseParser
from app.services.diagram_ai_template_repairer import DiagramAiTemplateRepairer
from app.services.diagram_semantic_validator import DiagramSemanticValidator
from app.services.openrouter_service import OpenRouterService


class DiagramAiService:
    MODEL_TEMPERATURE = 0.0
    MODEL_MAX_TOKENS = 9000

    def __init__(self) -> None:
        self.openrouter_service = OpenRouterService()
        self.prompt_builder = DiagramAiPromptBuilder()
        self.response_parser = DiagramAiResponseParser()
        self.template_repairer = DiagramAiTemplateRepairer()
        self.auto_repairer = DiagramAiAutoRepairer()
        self.semantic_validator = DiagramSemanticValidator()
        self.flowroad_builder = DiagramAiFlowRoadBuilder()
        self.error_serializer = DiagramAiErrorSerializer()

    async def generate_or_edit_diagram(
        self,
        request: DiagramAiRequest,
    ) -> DiagramAiResponse:
        raw_response = await self._call_model(request)

        compact_response = self._parse_repair_and_validate(
            raw_response=raw_response,
            request=request,
        )

        semantic_errors = self.semantic_validator.validate(
            diagram=compact_response.diagram,
            template_suggestions=compact_response.template_suggestions,
            existing_templates=request.existing_templates,
        )

        if semantic_errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": (
                        "La propuesta de IA tiene errores semánticos "
                        "y no es ejecutable todavía."
                    ),
                    "errors": semantic_errors,
                    "raw_response": raw_response,
                },
            )

        return self.flowroad_builder.build_flowroad_response(
            compact_response=compact_response,
            request=request,
        )

    async def generate_or_edit_diagram_raw(
        self,
        request: DiagramAiRequest,
    ) -> DiagramAiRawResponse:
        raw_response = await self._call_model(request)

        return DiagramAiRawResponse(
            message="Respuesta cruda generada correctamente.",
            raw_response=raw_response,
        )

    async def _call_model(self, request: DiagramAiRequest) -> str:
        system_prompt = self.prompt_builder.build_system_prompt()
        user_prompt = self.prompt_builder.build_user_prompt(request)

        return await self.openrouter_service.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            temperature=self.MODEL_TEMPERATURE,
            max_tokens=self.MODEL_MAX_TOKENS,
        )

    def _parse_repair_and_validate(
        self,
        raw_response: str,
        request: DiagramAiRequest,
    ) -> DiagramAiCompactResponse:
        parsed_response = self.response_parser.parse_json_response(
            raw_response,
        )

        # El modo real lo define el request del backend/frontend.
        # No confiamos en el valor que devuelva la IA porque puede copiar
        # el ejemplo del prompt y responder siempre "CREATE".
        parsed_response["mode"] = request.mode.value

        parsed_response = self.template_repairer.repair_missing_template_suggestions(
            parsed_response=parsed_response,
            request=request,
        )

        parsed_response = self.auto_repairer.repair(
            parsed_response=parsed_response,
            request=request,
        )

        # Segunda pasada: después del auto_repairer pueden aparecer nodos ACTION
        # nuevos o cambios que requieran completar sugerencias de plantilla.
        parsed_response = self.template_repairer.repair_missing_template_suggestions(
            parsed_response=parsed_response,
            request=request,
        )

        try:
            return DiagramAiCompactResponse.model_validate(
                parsed_response,
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "message": (
                        "La IA devolvió JSON compacto, pero no cumple "
                        "el formato esperado."
                    ),
                    "errors": self.error_serializer.serialize_validation_errors(
                        exc,
                    ),
                    "raw_response": raw_response,
                },
            ) from exc