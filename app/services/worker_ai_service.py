import json

from app.core.worker_ai_prompt import WORKER_AI_SYSTEM_PROMPT
from app.schemas.worker_ai_schemas import (
    WorkerAiAssistRequest,
    WorkerAiAssistResponse,
)
from app.services.openrouter_service import OpenRouterService


class WorkerAiService:
    def __init__(self) -> None:
        self.openrouter_service = OpenRouterService()

    async def assist_worker(
        self,
        request: WorkerAiAssistRequest,
    ) -> WorkerAiAssistResponse:
        context = {
            "task_name": request.task_name,
            "template_name": request.template_name,
            "fields": request.fields,
            "current_answers": request.current_answers,
            "process_history": request.process_history,
            "worker_note": request.worker_note,
        }

        user_prompt = f"""
Ayuda al trabajador a llenar o revisar esta plantilla de FlowRoad.

Contexto JSON:
{json.dumps(context, ensure_ascii=False, indent=2)}

Devuelve:
- resumen breve del contexto,
- sugerencias por campo,
- advertencias si faltan datos,
- comentario recomendado si aplica.

No inventes datos que no estén en el contexto.
"""

        raw_response = await self.openrouter_service.chat_completion(
            messages=[
                {"role": "system", "content": WORKER_AI_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=1200,
        )

        return WorkerAiAssistResponse(
            message="Asistencia generada correctamente.",
            raw_response=raw_response,
        )