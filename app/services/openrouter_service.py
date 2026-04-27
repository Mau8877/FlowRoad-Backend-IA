from typing import Any

import httpx
from fastapi import HTTPException, status

from app.config import get_settings


class OpenRouterService:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.settings.openrouter_site_url,
            "X-Title": self.settings.openrouter_app_name,
        }

        payload: dict[str, Any] = {
            "model": self.settings.openrouter_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self.settings.openrouter_base_url,
                    headers=headers,
                    json=payload,
                )

            response.raise_for_status()
            data = response.json()

            choices = data.get("choices", [])
            if not choices:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="OpenRouter no devolvió ninguna respuesta.",
                )

            message = choices[0].get("message", {})
            content = message.get("content")

            if not content:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="La respuesta del modelo vino vacía.",
                )

            return str(content)

        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Error de OpenRouter: {exc.response.text}",
            ) from exc

        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"No se pudo conectar con OpenRouter: {str(exc)}",
            ) from exc