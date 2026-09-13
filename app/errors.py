"""Map validation failures to deterministic field-level JSON errors."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    field_errors: list[dict[str, Any]] = []
    for error in exc.errors():
        location = ["body", *error.get("loc", ())[1:]]
        field_error = {
            "location": location,
            "code": error.get("type", "validation_error"),
            "message": error.get("msg", "Input is invalid."),
        }
        context = _json_safe(error.get("ctx"))
        if context is not None:
            field_error["context"] = context
        field_errors.append(field_error)

    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "The request failed domain validation; no decision was produced.",
                "fields": field_errors,
            }
        },
    )
