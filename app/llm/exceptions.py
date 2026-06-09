"""LLM-layer exceptions, surfaced as typed AppErrors at the API boundary."""

from __future__ import annotations

from app.errors import ProviderError, TimeoutError_, ValidationFailedError


class LLMError(ProviderError):
    code = "llm_error"


class LLMTimeout(TimeoutError_):
    code = "llm_timeout"


class LLMValidationError(ValidationFailedError):
    """Schema enforcement failed after instructor exhausted its retries.

    Carries the last raw completion + the validation errors for debugging.
    """

    code = "llm_validation_failed"

    def __init__(self, detail: str, raw: str | None = None, errors: object = None):
        super().__init__(detail, raw=raw, errors=errors)


class LLMProviderError(ProviderError):
    """MiniMax returned a non-2xx (auth, rate limit, 5xx)."""

    code = "llm_provider_error"
