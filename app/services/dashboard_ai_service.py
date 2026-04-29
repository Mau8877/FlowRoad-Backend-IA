import inspect
import json
import re
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from app.core.dashboard_ai_prompt import build_dashboard_bottleneck_prompt
from app.schemas.dashboard_ai_schemas import (
    DashboardAiAnalysisRequest,
    DashboardAiAnalysisResponse,
    DepartmentPendingTasks,
    PopularProcess,
)

try:
    from app.services.openrouter_service import OpenRouterService
except ImportError:
    OpenRouterService = None


class DashboardAiService:
    def __init__(self) -> None:
        self.openrouter_service = self._build_openrouter_service()

    async def analyze_bottleneck(
        self,
        request: DashboardAiAnalysisRequest,
    ) -> DashboardAiAnalysisResponse:
        fallback_analysis = self._build_local_analysis(request)

        if self.openrouter_service is None:
            return fallback_analysis.model_copy(
                update={
                    "provider_error": (
                        "OpenRouterService no está disponible. "
                        "Se usó análisis local."
                    )
                }
            )

        prompt = build_dashboard_bottleneck_prompt(
            request=request,
            fallback_analysis=fallback_analysis,
        )

        try:
            raw_response = await self._call_provider(prompt)
            parsed_response = self._parse_provider_json(raw_response)

            ai_response = DashboardAiAnalysisResponse.model_validate(
                parsed_response
            )

            return ai_response.model_copy(
                update={
                    "generated_by": "AI",
                    "generated_at": datetime.now(timezone.utc),
                    "provider_error": None,
                }
            )
        except Exception as exc:
            return fallback_analysis.model_copy(
                update={
                    "provider_error": (
                        "No se pudo usar el proveedor IA. "
                        f"Detalle: {str(exc)}"
                    )[:500]
                }
            )

    def _build_openrouter_service(self) -> Any | None:
        if OpenRouterService is None:
            return None

        try:
            return OpenRouterService()
        except Exception:
            return None

    async def _call_provider(self, prompt: str) -> Any:
        service = self.openrouter_service

        if service is None:
            raise RuntimeError("OpenRouterService no está inicializado.")

        messages = [
            {
                "role": "system",
                "content": (
                    "Eres un analista operativo de procesos empresariales. "
                    "Responde únicamente JSON válido, sin markdown."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]

        chat_completion = getattr(service, "chat_completion", None)

        if callable(chat_completion):
            result = chat_completion(
                messages=messages,
                temperature=0.2,
                max_tokens=900,
            )

            if inspect.isawaitable(result):
                result = await result

            return result

        method_names = (
            "generate_json",
            "complete_json",
            "generate_response",
            "generate_text",
            "generate",
            "complete",
            "chat",
            "ask",
        )

        last_error: Exception | None = None

        for method_name in method_names:
            method = getattr(service, method_name, None)

            if not callable(method):
                continue

            for call_style in ("messages_kw", "prompt_kw", "positional"):
                try:
                    result = self._call_method(method, prompt, call_style)

                    if inspect.isawaitable(result):
                        result = await result

                    return result
                except Exception as exc:
                    last_error = exc

        if last_error is not None:
            raise last_error

        raise RuntimeError(
            "No se encontró un método compatible en OpenRouterService."
        )

    def _call_method(
        self,
        method: Any,
        prompt: str,
        call_style: str,
    ) -> Any:
        if call_style == "positional":
            return method(prompt)

        if call_style == "prompt_kw":
            return method(prompt=prompt)

        if call_style == "messages_kw":
            return method(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Eres un analista operativo de procesos. "
                            "Responde únicamente JSON válido."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ]
            )

        raise ValueError("Estilo de llamada no soportado.")

    def _parse_provider_json(self, raw_response: Any) -> dict[str, Any]:
        if isinstance(raw_response, dict):
            return raw_response

        text = self._extract_text(raw_response)

        if not text:
            raise ValueError("La IA devolvió una respuesta vacía.")

        cleaned = self._remove_code_fences(text)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            json_match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)

            if not json_match:
                raise

            return json.loads(json_match.group(0))

    def _extract_text(self, raw_response: Any) -> str:
        if raw_response is None:
            return ""

        if isinstance(raw_response, str):
            return raw_response.strip()

        if isinstance(raw_response, dict):
            for key in ("content", "text", "message", "response", "result"):
                value = raw_response.get(key)

                if isinstance(value, str):
                    return value.strip()

            choices = raw_response.get("choices")

            if isinstance(choices, list) and choices:
                first_choice = choices[0]

                if isinstance(first_choice, dict):
                    message = first_choice.get("message")

                    if isinstance(message, dict):
                        content = message.get("content")

                        if isinstance(content, str):
                            return content.strip()

                    text = first_choice.get("text")

                    if isinstance(text, str):
                        return text.strip()

        return str(raw_response).strip()

    def _remove_code_fences(self, text: str) -> str:
        cleaned = text.strip()

        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
            cleaned = re.sub(r"```$", "", cleaned).strip()

        return cleaned

    def _build_local_analysis(
        self,
        request: DashboardAiAnalysisRequest,
    ) -> DashboardAiAnalysisResponse:
        severity_score = self._calculate_severity_score(request)
        severity = self._resolve_severity(severity_score)
        severity_label = self._resolve_severity_label(severity)

        main_bottleneck = self._resolve_main_bottleneck(request)
        evidence = self._build_evidence(request)
        recommendations = self._build_recommendations(
            request=request,
            main_bottleneck=main_bottleneck,
        )
        summary = self._build_summary(
            request=request,
            severity=severity,
            main_bottleneck=main_bottleneck,
        )

        return DashboardAiAnalysisResponse(
            summary=summary,
            severity=severity,
            severity_label=severity_label,
            main_bottleneck=main_bottleneck,
            evidence=evidence,
            recommendations=recommendations,
            generated_by="LOCAL_FALLBACK",
            generated_at=datetime.now(timezone.utc),
            provider_error=None,
        )

    def _calculate_severity_score(
        self,
        request: DashboardAiAnalysisRequest,
    ) -> int:
        if request.total_processes <= 0:
            return 0

        score = 0

        pending_assignment_ratio = (
            request.pending_assignment_processes / request.total_processes
        )

        if request.pending_assignment_processes > 0:
            score += 1

        if pending_assignment_ratio >= 0.25:
            score += 2

        if request.completion_rate < 60:
            score += 1

        if request.completion_rate < 35:
            score += 2

        if request.average_completion_time_minutes >= 480:
            score += 1

        if request.average_completion_time_minutes >= 1440:
            score += 2

        top_department = self._top_pending_department(request)

        if top_department is not None:
            if top_department.pending_tasks >= 10:
                score += 3
            elif top_department.pending_tasks >= 5:
                score += 2
            elif top_department.pending_tasks > 0:
                score += 1

        cancelled_ratio = request.cancelled_processes / request.total_processes

        if cancelled_ratio >= 0.15:
            score += 1

        return score

    def _resolve_severity(self, score: int) -> str:
        if score >= 5:
            return "HIGH"

        if score >= 2:
            return "MEDIUM"

        return "LOW"

    def _resolve_severity_label(self, severity: str) -> str:
        labels = {
            "LOW": "Baja",
            "MEDIUM": "Media",
            "HIGH": "Alta",
        }

        return labels.get(severity, "Baja")

    def _resolve_main_bottleneck(
        self,
        request: DashboardAiAnalysisRequest,
    ) -> str:
        top_department = self._top_pending_department(request)

        if top_department is not None and top_department.pending_tasks > 0:
            return (
                "Concentración de tareas pendientes en "
                f"{top_department.department_name}"
            )

        if request.pending_assignment_processes > 0:
            return "Procesos pendientes de asignación"

        if request.average_completion_time_minutes >= 480:
            return "Tiempo promedio de finalización elevado"

        if request.total_processes > 0 and request.completion_rate < 60:
            return "Tasa de finalización baja"

        if request.total_processes <= 0:
            return "Datos insuficientes para detectar cuellos de botella"

        return "No se detecta un cuello de botella crítico"

    def _build_evidence(
        self,
        request: DashboardAiAnalysisRequest,
    ) -> list[str]:
        evidence = [
            f"Total de trámites analizados: {request.total_processes}.",
            f"Tasa de finalización: {request.completion_rate}%.",
            (
                "Tiempo promedio de finalización: "
                f"{request.average_completion_time_label}."
            ),
        ]

        if request.pending_assignment_processes > 0:
            evidence.append(
                "Existen "
                f"{request.pending_assignment_processes} procesos pendientes "
                "de asignación."
            )

        if request.cancelled_processes > 0:
            evidence.append(
                f"Existen {request.cancelled_processes} procesos cancelados."
            )

        top_department = self._top_pending_department(request)

        if top_department is not None and top_department.pending_tasks > 0:
            evidence.append(
                "El departamento con mayor carga pendiente es "
                f"{top_department.department_name}, con "
                f"{top_department.pending_tasks} tareas pendientes."
            )
        else:
            evidence.append(
                "No se registran tareas pendientes agrupadas por departamento."
            )

        top_process = self._top_used_process(request)

        if top_process is not None:
            evidence.append(
                "El proceso más usado es "
                f"{top_process.diagram_name}, con "
                f"{top_process.total_instances} instancias."
            )

        return evidence

    def _build_recommendations(
        self,
        request: DashboardAiAnalysisRequest,
        main_bottleneck: str,
    ) -> list[str]:
        recommendations: list[str] = []

        if request.total_processes <= 0:
            return [
                "Crear o ejecutar más trámites para contar con datos suficientes.",
                "Revisar nuevamente el dashboard cuando existan instancias reales.",
            ]

        if "departamento" in main_bottleneck.lower():
            recommendations.extend(
                [
                    "Revisar la distribución de tareas del departamento con mayor carga.",
                    "Validar si existen trabajadores activos suficientes para el área.",
                    "Redistribuir asignaciones si hay usuarios con carga desigual.",
                ]
            )

        if request.pending_assignment_processes > 0:
            recommendations.extend(
                [
                    "Revisar nodos ACTION sin departamento o cargo asignado.",
                    "Validar que existan usuarios activos para los departamentos requeridos.",
                    "Corregir diagramas que generen procesos en estado pendiente de asignación.",
                ]
            )

        if request.average_completion_time_minutes >= 480:
            recommendations.append(
                "Revisar las actividades con mayor duración para reducir tiempos de espera."
            )

        if request.completion_rate < 60:
            recommendations.append(
                "Analizar por qué una parte importante de los trámites no llega a completarse."
            )

        if not recommendations:
            recommendations.extend(
                [
                    "Mantener monitoreo periódico de los KPIs para detectar tendencias.",
                    "Priorizar la revisión de los procesos más utilizados.",
                ]
            )

        return self._deduplicate(recommendations)[:5]

    def _build_summary(
        self,
        request: DashboardAiAnalysisRequest,
        severity: str,
        main_bottleneck: str,
    ) -> str:
        if request.total_processes <= 0:
            return (
                "No existen suficientes trámites registrados para realizar "
                "un análisis operativo confiable."
            )

        if main_bottleneck == "No se detecta un cuello de botella crítico":
            return (
                "Los indicadores actuales no muestran un cuello de botella "
                "crítico. Se recomienda continuar monitoreando la evolución "
                "de los procesos."
            )

        if severity == "HIGH":
            return (
                "Se detecta un posible cuello de botella de alta prioridad: "
                f"{main_bottleneck}. Requiere revisión operativa inmediata."
            )

        if severity == "MEDIUM":
            return (
                "Se detecta un posible cuello de botella de prioridad media: "
                f"{main_bottleneck}. Conviene revisar la operación antes de "
                "que afecte más trámites."
            )

        return (
            "Se identifican señales leves de posible cuello de botella en: "
            f"{main_bottleneck}. Por ahora el impacto parece controlado."
        )

    def _top_pending_department(
        self,
        request: DashboardAiAnalysisRequest,
    ) -> DepartmentPendingTasks | None:
        if not request.pending_tasks_by_department:
            return None

        return max(
            request.pending_tasks_by_department,
            key=lambda item: item.pending_tasks,
        )

    def _top_used_process(
        self,
        request: DashboardAiAnalysisRequest,
    ) -> PopularProcess | None:
        if not request.most_used_processes:
            return None

        return max(
            request.most_used_processes,
            key=lambda item: item.total_instances,
        )

    def _deduplicate(self, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()

        for value in values:
            normalized = value.strip().lower()

            if not normalized or normalized in seen:
                continue

            seen.add(normalized)
            result.append(value)

        return result