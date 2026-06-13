"""Multi-provider backend factory for the structured-output engine.

Each LLM provider is wrapped by instructor so the rest of the app calls one
uniform `generate(response_model=...)` regardless of backend. OpenAI, MiniMax and
Gemini are all OpenAI-compatible (instructor.from_openai with different
base_url/key); Anthropic uses its own SDK. Mode selection per provider/model
keeps structured output strict on each backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import instructor

from app.config import Settings
from app.errors import ProviderError

ProviderName = Literal["minimax", "openai", "anthropic", "gemini", "atlas"]

# Per-model structured-output Mode overrides (else the provider default is used).
# NOTE: MiniMax's OpenAI-compatible endpoint rejects `response_format`
# (json_object/json_schema), so MiniMax models must NOT use Mode.JSON. They fall
# back to the provider default MD_JSON (schema injected into the prompt, parsed by
# instructor) — confirmed against the live API.
_MODEL_MODE: dict[str, instructor.Mode] = {}
_PROVIDER_DEFAULT_MODE: dict[str, instructor.Mode] = {
    "minimax": instructor.Mode.MD_JSON,
    "openai": instructor.Mode.TOOLS,
    "gemini": instructor.Mode.JSON,
    "anthropic": instructor.Mode.ANTHROPIC_TOOLS,
    # AtlasCloud-hosted open models (qwen3-vl etc.): schema-in-prompt is safest.
    "atlas": instructor.Mode.MD_JSON,
}


@dataclass
class Backend:
    """A ready instructor client plus the metadata generate() needs."""

    client: instructor.AsyncInstructor
    kind: Literal["openai", "anthropic"]
    default_model: str
    mode: instructor.Mode


def resolve_mode(provider: ProviderName, model: str) -> instructor.Mode:
    return _MODEL_MODE.get(model, _PROVIDER_DEFAULT_MODE[provider])


def default_model(provider: ProviderName, settings: Settings) -> str:
    return {
        "minimax": settings.minimax_text_model,
        "openai": settings.openai_model,
        "anthropic": settings.anthropic_model,
        "gemini": settings.gemini_model,
        "atlas": settings.atlas_vl_model,
    }[provider]


def _resolved_creds(provider: ProviderName, settings: Settings) -> tuple[str, str | None]:
    """The (api_key, base_url) the live client should use.

    Prefers a persisted ProviderSecret (set from the Settings UI) over the env
    value, falling back to env/config defaults. Opens a short-lived session on
    the shared engine; on any DB/import error it degrades to env-only so the LLM
    path never breaks because of settings plumbing.
    """
    # Env/config defaults first (used as the fallback below).
    env = {
        "minimax": (settings.minimax_api_key, settings.minimax_base_url),
        "openai": (settings.openai_api_key, settings.openai_base_url),
        "gemini": (settings.gemini_api_key, settings.gemini_base_url),
        "atlas": (settings.atlascloud_api_key, settings.atlas_llm_base_url),
        "anthropic": (settings.anthropic_api_key, None),
    }
    key, base_url = env[provider]
    try:
        from sqlmodel import Session

        from app.database import engine
        from app.services import settings_service

        with Session(engine) as session:
            key = settings_service.effective_key(session, provider, settings)
            base_url = settings_service.effective_base_url(session, provider, settings)
    except Exception:
        pass
    return key, base_url


def build_backend(
    provider: ProviderName, model: str, settings: Settings, timeout_s: float
) -> Backend:
    mode = resolve_mode(provider, model)

    if provider in ("minimax", "openai", "gemini", "atlas"):
        from openai import AsyncOpenAI

        key, base_url = _resolved_creds(provider, settings)
        if not key:
            raise ProviderError(f"{provider} API key is not configured")
        raw = AsyncOpenAI(api_key=key, base_url=base_url, timeout=timeout_s)
        return Backend(instructor.from_openai(raw, mode=mode), "openai", model, mode)

    if provider == "anthropic":
        from anthropic import AsyncAnthropic

        key, _ = _resolved_creds(provider, settings)
        if not key:
            raise ProviderError("anthropic API key is not configured")
        raw = AsyncAnthropic(api_key=key, timeout=timeout_s)
        return Backend(
            instructor.from_anthropic(raw, mode=mode), "anthropic", model, mode
        )

    raise ProviderError(f"unknown LLM provider '{provider}'")
