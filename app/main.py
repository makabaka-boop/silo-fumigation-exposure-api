"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.errors import request_validation_exception_handler
from app.routes import router

app = FastAPI(
    title="Phosphine Exposure Verification API",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_exception_handler(
    RequestValidationError,
    request_validation_exception_handler,
)
app.include_router(router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
