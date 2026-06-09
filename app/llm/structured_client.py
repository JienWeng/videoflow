"""The structured-output engine (multi-provider).

One reusable async `generate(response_model=...)` that every agent calls to get a
validated Pydantic object. Routing is per-agent via the skill registry: a skill
names the provider (MiniMax / OpenAI / Anthropic / Gemini) and model; this engine
builds the right instructor backend, injects the schema, and on a Pydantic
ValidationError re-prompts up to `max_retries` times. The enforcement contract is
identical on every backend — only the wiring differs.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TypeVar

import instructor
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.llm.exceptions import LLMProviderError, LLMTimeout, LLMValidationError
from app.llm.providers import Backend, ProviderName, build_backend, default_model
from app.llm.skills import get_skill

logger = logging.getLogger("videoflow.llm")

T = TypeVar("T", bound=BaseModel)


class StructuredLLMClient:
    """Shared, dependency-injected multi-provider instructor wrapper."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._backends: dict[tuple[str, str], Backend] = {}

    def _backend(self, provider: ProviderName, model: str, timeout_s: float) -> Backend:
        key = (provider, model)
        if key not in self._backends:
            self._backends[key] = build_backend(
                provider, model, self._settings, timeout_s
            )
        return self._backends[key]

    async def generate(
        self,
        *,
        response_model: type[T],
        user_prompt: str,
        system_prompt: str | None = None,
        agent: str | None = None,
        context: dict | None = None,
        provider: ProviderName | None = None,
        model: str | None = None,
        max_retries: int | None = None,
        timeout_s: float | None = None,
        temperature: float | None = None,
        max_tokens: int = 4096,
        mode: instructor.Mode | None = None,
    ) -> T:
        skill = get_skill(agent) if agent else None

        # Resolve config: explicit kwarg > skill > settings/default.
        provider = provider or (skill.provider if skill else "minimax")
        if model is None:
            model = (skill.model if skill and skill.model else None) or default_model(
                provider, self._settings
            )
        if temperature is None:
            temperature = skill.temperature if skill else self._settings.llm_temperature
        if max_retries is None:
            max_retries = skill.max_retries if skill else self._settings.llm_max_retries
        timeout_s = timeout_s if timeout_s is not None else self._settings.llm_timeout_s

        if system_prompt is None and skill is not None:
            system_prompt = _format(skill.system_prompt, context)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        backend = self._backend(provider, model, timeout_s)
        if mode is not None:
            # Caller-forced mode requires a backend built with that mode.
            backend = build_backend(provider, model, self._settings, timeout_s)

        kwargs: dict = dict(
            model=model,
            response_model=response_model,
            messages=messages,
            max_retries=max_retries,
            temperature=temperature,
        )
        if backend.kind == "anthropic":
            kwargs["max_tokens"] = max_tokens

        try:
            return await asyncio.wait_for(
                backend.client.chat.completions.create(**kwargs), timeout=timeout_s
            )
        except asyncio.TimeoutError as exc:
            logger.warning("LLM timeout %.1fs (agent=%s, provider=%s)", timeout_s, agent, provider)
            raise LLMTimeout(f"LLM call timed out after {timeout_s}s") from exc
        except Exception as exc:
            raw = _extract_raw(exc)
            errors = _extract_errors(exc)
            if raw is not None or errors is not None:
                logger.error(
                    "Schema enforcement failed (agent=%s, provider=%s, model=%s). Raw: %s",
                    agent, provider, response_model.__name__, raw,
                )
                raise LLMValidationError(
                    f"Failed to produce valid {response_model.__name__} "
                    f"after {max_retries} retries",
                    raw=raw,
                    errors=errors,
                ) from exc
            logger.error("LLM provider error (agent=%s, provider=%s): %s", agent, provider, exc)
            raise LLMProviderError(f"{provider} error: {exc}") from exc


def _format(template: str, context: dict | None) -> str:
    if not context:
        return template
    try:
        return template.format(**context)
    except (KeyError, IndexError):
        return template


def _extract_raw(exc: Exception) -> str | None:
    completion = getattr(exc, "last_completion", None)
    if completion is None:
        return None
    try:
        return completion.choices[0].message.content
    except Exception:
        return str(completion)


def _extract_errors(exc: Exception) -> object | None:
    cause = exc.__cause__ or exc.__context__
    if cause is not None and hasattr(cause, "errors"):
        try:
            return cause.errors()
        except Exception:
            return str(cause)
    if hasattr(exc, "errors"):
        try:
            return exc.errors()
        except Exception:
            return None
    return None


_singleton: StructuredLLMClient | None = None


def get_llm_client() -> StructuredLLMClient:
    global _singleton
    if _singleton is None:
        _singleton = StructuredLLMClient()
    return _singleton
