import json

from app.schemas.dashboard_ai_schemas import (
    DashboardAiAnalysisRequest,
    DashboardAiAnalysisResponse,
)


def build_dashboard_bottleneck_prompt(
    request: DashboardAiAnalysisRequest,
    fallback_analysis: DashboardAiAnalysisResponse,
) -> str:
    dashboard_data = request.model_dump(by_alias=True, mode="json")
    fallback_data = fallback_analysis.model_dump(by_alias=True, mode="json")

    return f"""
Eres un analista operativo especializado en procesos empresariales y KPIs.

Tu tarea:
Analizar los KPIs de FlowRoad y detectar posibles cuellos de botella
operativos.

Reglas obligatorias:
1. No inventes datos.
2. Usa únicamente la información del JSON recibido.
3. No digas que hay un cuello de botella si los datos no lo sostienen.
4. Si los datos son insuficientes, dilo claramente.
5. El análisis debe ser breve, profesional y accionable.
6. Devuelve únicamente JSON válido.
7. No uses markdown.
8. No envuelvas la respuesta en ```json.
9. La severidad solo puede ser LOW, MEDIUM o HIGH.

Criterios de análisis:
- Muchos procesos en PENDING_ASSIGNMENT pueden indicar problema de asignación.
- Muchas tareas pendientes en un departamento pueden indicar saturación del área.
- Baja tasa de finalización puede indicar problemas de eficiencia.
- Tiempo promedio alto puede indicar demora operativa.
- Procesos muy usados pueden requerir priorización o revisión.
- Si no hay tareas pendientes por departamento, no asumas saturación de áreas.

JSON de KPIs:
{json.dumps(dashboard_data, ensure_ascii=False, indent=2)}

Análisis local de referencia:
{json.dumps(fallback_data, ensure_ascii=False, indent=2)}

Formato exacto esperado:
{{
  "summary": "Resumen profesional en una o dos frases.",
  "severity": "LOW | MEDIUM | HIGH",
  "severityLabel": "Baja | Media | Alta",
  "mainBottleneck": "Nombre del cuello de botella principal.",
  "evidence": [
    "Evidencia concreta basada en los KPIs."
  ],
  "recommendations": [
    "Recomendación accionable."
  ]
}}
""".strip()