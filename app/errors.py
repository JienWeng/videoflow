"""Domain exceptions and their FastAPI exception handlers.

Providers and the LLM client raise typed exceptions; handlers map them to
structured HTTP responses. Raw httpx/openai errors never reach the client.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base for all domain errors. `status_code` drives the HTTP response."""

    status_code = 500
    code = "internal_error"

    def __init__(self, detail: str = "", **extra: object) -> None:
        super().__init__(detail)
        self.detail = detail or self.__class__.__name__
        self.extra = extra


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ValidationFailedError(AppError):
    status_code = 422
    code = "validation_failed"


class UnsupportedProviderError(AppError):
    status_code = 400
    code = "unsupported_provider"


class ProviderError(AppError):
    """Upstream provider (MiniMax / AtlasCloud) returned an error."""

    status_code = 502
    code = "provider_error"


class TimeoutError_(AppError):
    status_code = 504
    code = "timeout"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.code, "detail": exc.detail, **exc.extra},
        )
