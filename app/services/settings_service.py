"""Settings service — per-agent LLM provider/model selection.

Two concerns:

1. **Catalog** of what's actually usable: which providers have a key configured
   and a short curated list of known model ids per provider. The UI only lets the
   user pick from this (no free-typing for v1).
2. **Overrides**: a thin store that lets the user repoint an agent at a different
   configured provider/model. Overrides live both in the DB (`agent_settings`) and
   in an in-process mirror (`skills._OVERRIDES`) that the structured client reads
   when routing. The DB is the source of truth; the mirror is loaded at startup
   and kept in sync on every write so live agent calls pick up changes instantly.
"""

from __future__ import annotations

from sqlmodel import Session, select

from app.config import Settings, get_settings
from app.errors import NotFoundError, ValidationFailedError
from app.llm import skills
from app.llm.providers import ProviderName, default_model
from app.models.base import utcnow
from app.models.setting import AgentSetting

# Curated, short "known options" per provider. The provider's configured default
# model is always merged in (so a custom env model still appears + is selectable).
_KNOWN_MODELS: dict[str, list[str]] = {
    "minimax": ["MiniMax-Text-01", "MiniMax-M2"],
    "openai": ["gpt-4o-mini", "gpt-4o"],
    "anthropic": ["claude-sonnet-4-6", "claude-opus-4-8"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro"],
    "atlas": ["qwen/qwen3-vl-30b-a3b-instruct", "glm-5v"],
}

# All providers the UI knows about (order is display order).
PROVIDERS: list[ProviderName] = ["minimax", "openai", "anthropic", "gemini", "atlas"]


def _key(provider: str, settings: Settings) -> str:
    return {
        "minimax": settings.minimax_api_key,
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
        "gemini": settings.gemini_api_key,
        "atlas": settings.atlascloud_api_key,
    }[provider]


def is_configured(provider: str, settings: Settings) -> bool:
    return bool(_key(provider, settings))


def models_for(provider: str, settings: Settings) -> list[str]:
    """Curated model ids for a provider, with the configured default merged in."""
    models = list(_KNOWN_MODELS.get(provider, []))
    dflt = default_model(provider, settings)  # type: ignore[arg-type]
    if dflt and dflt not in models:
        models.insert(0, dflt)
    return models


def available_providers(settings: Settings | None = None) -> list[dict]:
    """Catalog: for each provider {name, configured, models, default_model}."""
    settings = settings or get_settings()
    return [
        {
            "name": p,
            "configured": is_configured(p, settings),
            "models": models_for(p, settings),
            "default_model": default_model(p, settings),  # type: ignore[arg-type]
        }
        for p in PROVIDERS
    ]


def get_overrides(session: Session) -> dict[str, dict[str, str | None]]:
    rows = session.exec(select(AgentSetting)).all()
    return {r.agent: {"provider": r.provider, "model": r.model} for r in rows}


def load_overrides(session: Session) -> None:
    """Populate the in-process mirror from the DB (called at startup)."""
    skills.clear_overrides()
    for agent, ov in get_overrides(session).items():
        skills.set_override(agent, ov["provider"], ov["model"])


def effective_skill(session: Session, agent: str):
    """Base skill merged with the agent's DB override. Ensures the in-process
    mirror reflects the DB before resolving (keeps reads honest in tests)."""
    load_overrides(session)
    return skills.get_effective_skill(agent)


def _validate(provider: str | None, model: str | None, settings: Settings) -> None:
    if provider is None and model is None:
        return  # clearing — always allowed
    if provider is None:
        raise ValidationFailedError("provider is required when setting a model")
    if provider not in PROVIDERS:
        raise ValidationFailedError(f"unknown provider '{provider}'")
    if not is_configured(provider, settings):
        raise ValidationFailedError(
            f"provider '{provider}' is not configured (missing API key)"
        )
    if model is not None and model not in models_for(provider, settings):
        raise ValidationFailedError(
            f"model '{model}' is not a known option for '{provider}'"
        )


def set_override(
    session: Session,
    agent: str,
    provider: str | None,
    model: str | None,
    settings: Settings | None = None,
) -> dict:
    """Set or clear an agent override. Writes the DB and the in-process mirror.
    Validates the provider is configured and the model is a known option.
    Nulls in both fields clear the override (revert to skill default)."""
    settings = settings or get_settings()
    if skills.get_skill(agent) is None:
        raise NotFoundError(f"unknown agent '{agent}'")
    _validate(provider, model, settings)

    row = session.exec(select(AgentSetting).where(AgentSetting.agent == agent)).first()
    if provider is None and model is None:
        if row is not None:
            session.delete(row)
            session.commit()
        skills.set_override(agent, None, None)
        return agent_view(agent, settings)

    if row is None:
        row = AgentSetting(agent=agent, provider=provider, model=model)
        session.add(row)
    else:
        row.provider = provider
        row.model = model
        row.updated_at = utcnow()
        session.add(row)
    session.commit()
    skills.set_override(agent, provider, model)
    return agent_view(agent, settings)


def agent_view(agent: str, settings: Settings | None = None) -> dict:
    """The effective + default routing for one agent, for the API/UI."""
    settings = settings or get_settings()
    base = skills.get_skill(agent)
    eff = skills.get_effective_skill(agent)
    return {
        "agent": agent,
        "label": skills.agent_label(agent),
        "provider": eff.provider,
        "model": eff.model or default_model(eff.provider, settings),  # type: ignore[arg-type]
        "default_provider": base.provider,
        "default_model": base.model or default_model(base.provider, settings),  # type: ignore[arg-type]
    }


def all_agents(session: Session, settings: Settings | None = None) -> list[dict]:
    settings = settings or get_settings()
    load_overrides(session)
    return [agent_view(a, settings) for a in skills.SKILLS]
