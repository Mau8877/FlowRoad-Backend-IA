import json
from typing import Any

from app.core.diagram_ai_prompt import DIAGRAM_AI_SYSTEM_PROMPT
from app.schemas.diagram_ai_schemas import DiagramAiRequest


class DiagramAiPromptBuilder:
    def build_system_prompt(self) -> str:
        return DIAGRAM_AI_SYSTEM_PROMPT

    def build_user_prompt(self, request: DiagramAiRequest) -> str:
        context = self.build_context(request)

        return f"""
Necesito que generes o modifiques una propuesta compacta de diagrama FlowRoad.

Modo de trabajo:
{request.mode.value}

Instrucción del usuario:
{request.user_message}

Contexto disponible en JSON:
{json.dumps(context, ensure_ascii=False, indent=2)}

Responde exclusivamente con JSON válido.
No uses Markdown.
No uses bloque ```json.
No escribas texto fuera del JSON.

No devuelvas el JSON visual completo.
No devuelvas attrs, router, connector, position, size, vertices ni labels visuales.
Solo devuelve nodes, links y template_suggestions en formato compacto.

La respuesta debe cumplir esta estructura exacta:

{{
  "message": "Mensaje breve para el usuario",
  "mode": "{request.mode.value}",
  "diagram": {{
    "name": "Nombre del diagrama",
    "description": "Descripción del diagrama",
    "nodes": [
      {{
        "id": "node-inicio",
        "type": "INITIAL",
        "name": "Inicio",
        "department_id": "id-real-departamento"
      }}
    ],
    "links": [
      {{
        "id": "link-1",
        "source_id": "node-inicio",
        "target_id": "node-siguiente",
        "label": null
      }}
    ]
  }},
  "template_suggestions": [],
  "warnings": [],
  "changes_summary": []
}}

Reglas críticas:
- Usa únicamente department_id reales del contexto.
- Cada ACTION debe tener template_suggestions.
- Cada DECISION debe estar precedida por un ACTION con SELECT compatible.
- Todo link que salga desde DECISION debe tener label.
- Si usas plantilla existente, strategy debe ser USE_EXISTING_TEMPLATE.
- Si propones plantilla nueva, strategy debe ser CREATE_NEW_TEMPLATE.
- Usa snake_case.
- Si el usuario menciona recepción, solicitud, registro inicial o atención inicial,
  crea un ACTION inicial para esa etapa antes de avanzar a otra área.
- Si propones un SELECT decisorio en una plantilla, crea un DECISION inmediatamente
  después de ese ACTION.
- Si no creas DECISION después de un ACTION, evita poner SELECT decisorio en su plantilla.
"""

    def build_context(self, request: DiagramAiRequest) -> dict[str, Any]:
        return {
            "mode": request.mode.value,
            "user_message": request.user_message,
            "current_diagram": request.current_diagram,
            "available_departments": [
                department.model_dump()
                for department in request.available_departments
            ],
            "existing_templates": [
                template.model_dump()
                for template in request.existing_templates
            ],
        }