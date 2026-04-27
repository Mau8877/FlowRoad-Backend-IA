from typing import Any

from pydantic import ValidationError


class DiagramAiErrorSerializer:
    def serialize_validation_errors(
        self,
        exc: ValidationError,
    ) -> list[dict[str, Any]]:
        serializable_errors: list[dict[str, Any]] = []

        for error in exc.errors():
            safe_error = {
                "type": error.get("type"),
                "loc": list(error.get("loc", [])),
                "msg": error.get("msg"),
                "input": error.get("input"),
                "url": error.get("url"),
            }

            ctx = error.get("ctx")
            if ctx:
                safe_error["ctx"] = {
                    key: str(value)
                    for key, value in ctx.items()
                }

            serializable_errors.append(safe_error)

        return serializable_errors