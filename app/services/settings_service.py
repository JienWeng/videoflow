"""Settings service — the configurability foundation.

Four concerns:

1. **Provider catalog & secrets**: which providers are configured (DB key OR env
   key) and a short list of *suggested* models per provider. Keys/base-urls are
   persisted in `provider_secrets` so they survive restarts and can be edited
   from the UI; the live LLM/AtlasCloud clients prefer the DB value over `.env`.
2. **App defaults resolver**: a generic key/value store (`app_settings`) overlaid
   in precedence project-override -> global -> config default, so things like the
   default aspect ratio or caption style are user-configurable without a restart.
3. **Agent overrides**: a thin store that repoints an agent at a different
   provider/model. Lives in the DB (`agent_settings`) and an in-process mirror
   (`skills._OVERRIDES`) the structured client reads when routing. Model ids are
   now FREE-TYPED — any non-empty model is accepted for a configured provider;
   the curated lists are suggestions only.
4. **Connection testing**: a cheap call per provider to confirm a key works.
"""

from __future__ import annotations

import base64
import re
import time

from sqlmodel import Session, select

from app.config import Settings, get_settings, invalidate_settings_cache
from app.errors import NotFoundError, ValidationFailedError
from app.llm import skills
from app.llm.providers import ProviderName, default_model
from app.llm.connections import catalog, definition, env_value
from app.models.base import utcnow
from app.models.setting import AgentSetting, AppSetting, ProviderSecret

# Curated, short "suggested options" per provider. These are hints for the UI
# only — the user may free-type any model id for a configured provider. The
# provider's configured default model is always merged in.
_KNOWN_MODELS: dict[str, list[str]] = {
    "minimax": ["MiniMax-Text-01", "MiniMax-M2"],
    "openai": ["gpt-5.6-luna", "gpt-4o-mini", "gpt-4o"],
    "deepseek": ["deepseek-v4-flash", "deepseek-v4-pro"],
    "anthropic": ["claude-sonnet-4-6", "claude-opus-4-8"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro"],
    "atlas": ["qwen/qwen3-vl-30b-a3b-instruct", "glm-5v"],
}

# All providers the UI knows about (order is display order).
PROVIDERS: list[ProviderName] = list(catalog())


# ---------------------------------------------------------------------------
# App-default keys: name -> Settings attribute holding the config default.
# The resolver overlays app_settings rows on top of these config defaults.
# ---------------------------------------------------------------------------
APP_SETTING_DEFAULTS: dict[str, str] = {
    "default_aspect_ratio": "default_aspect_ratio",
    "default_video_provider": "default_video_provider",
    "default_image_provider": "default_image_provider",
    "default_scene_duration": "default_scene_duration",
    "caption_style": "caption_style",
    "caption_language": "caption_language",
    "whisper_model": "whisper_model",
    "dialogue_language": "dialogue_language",
    "image_model": "atlas_image_model",
    "ref_image_model": "atlas_image_ref_model",
    "video_model": "atlas_video_model",
    "vl_model": "atlas_vl_model",
    "max_video_refs": "atlas_video_max_refs",
    "render_negatives": "render_negatives",
}
APP_SETTING_KEYS: list[str] = list(APP_SETTING_DEFAULTS)


# ---------------------------------------------------------------------------
# Provider secrets — light obfuscation (base64, NOT crypto) so keys aren't
# plain-text at rest in the local SQLite file. This is intentional: single-user
# local app; the threat model is "casual grep", not a determined attacker.
# ---------------------------------------------------------------------------
def _obfuscate(raw: str) -> str:
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")


def _deobfuscate(stored: str) -> str:
    if not stored:
        return ""
    try:
        return base64.b64decode(stored.encode("ascii")).decode("utf-8")
    except Exception:
        # Tolerate a value that was somehow stored un-obfuscated.
        return stored


def _mask(raw: str) -> str:
    """A safe, non-reversible preview of a key: show only the last 4 chars."""
    if not raw:
        return ""
    if len(raw) <= 4:
        return "•" * len(raw)
    return "••••" + raw[-4:]


# Matches sk-/key-shaped secrets (incl. partially-masked fingerprints a 401 body
# might echo, e.g. "sk-...AB12" or "sk-************AB12").
_KEYISH = re.compile(r"\b(?:sk|key)-[A-Za-z0-9_\-•*\.]+", re.IGNORECASE)


def _sanitize_connection_error(exc: Exception) -> str:
    """A concise, secret-free message for a failed connection test.

    Provider SDK errors can echo a partially-masked key fingerprint in their 401
    body, so we never surface the raw error verbatim. When an HTTP status is
    available we return e.g. "authentication failed (HTTP 401)"; otherwise a
    generic message. Any sk-/key-shaped token is stripped from the detail as a
    belt-and-suspenders guard.
    """
    status = getattr(exc, "status_code", None)
    if status is None:
        resp = getattr(exc, "response", None)
        status = getattr(resp, "status_code", None)

    if status in (401, 403):
        return f"authentication failed (HTTP {status})"
    if status is not None:
        return f"connection failed (HTTP {status})"

    detail = _KEYISH.sub("[redacted]", str(exc)).strip()
    return f"connection failed: {detail[:200]}" if detail else "connection failed"


def _secret_row(session: Session, provider: str) -> ProviderSecret | None:
    return session.exec(
        select(ProviderSecret).where(ProviderSecret.provider == provider)
    ).first()


def db_provider_key(session: Session, provider: str) -> str | None:
    """The deobfuscated API key persisted for *provider*, or None if no row."""
    row = _secret_row(session, provider)
    if row is None or not row.api_key:
        return None
    return _deobfuscate(row.api_key)


def db_provider_base_url(session: Session, provider: str) -> str | None:
    row = _secret_row(session, provider)
    return row.base_url if row else None


# ---------------------------------------------------------------------------
# Provider config (env-or-DB).
# ---------------------------------------------------------------------------
def _env_key(provider: str, settings: Settings) -> str:
    return {
        "minimax": settings.minimax_api_key,
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
        "gemini": settings.gemini_api_key,
        "atlas": settings.atlascloud_api_key,
    }.get(provider, env_value(provider, "API_KEY"))


def _env_base_url(provider: str, settings: Settings) -> str | None:
    return {
        "minimax": settings.minimax_base_url,
        "openai": settings.openai_base_url,
        "anthropic": env_value(provider, "BASE_URL", "https://api.anthropic.com"),
        "gemini": settings.gemini_base_url,
        # The LLM (chat) endpoint, NOT the image/video gateway.
        "atlas": settings.atlas_llm_base_url,
    }.get(provider, env_value(provider, "BASE_URL", definition(provider)["url"]))


def effective_key(session: Session | None, provider: str, settings: Settings) -> str:
    """The API key the live clients should use: DB secret wins over env."""
    if session is not None:
        db = db_provider_key(session, provider)
        if db:
            return db
    return _env_key(provider, settings)


def effective_base_url(
    session: Session | None, provider: str, settings: Settings
) -> str | None:
    """The base url for *provider*: DB override wins over env/config default."""
    if session is not None:
        db = db_provider_base_url(session, provider)
        if db:
            return db
        entry = definition(provider, session)
        if provider not in PROVIDERS and entry["url"]:
            return entry["url"]
    return _env_base_url(provider, settings)


def is_configured(
    provider: str,
    settings: Settings | None = None,
    session: Session | None = None,
) -> bool:
    """True if *provider* has a usable API key — from the DB OR the environment."""
    settings = settings or get_settings()
    if definition(provider, session)["protocol"] == "codex":
        from app.llm.connection_client import codex_status
        return codex_status()
    return bool(effective_key(session, provider, settings))


def get_provider_config(session: Session, provider: str) -> dict:
    """The UI view of a provider's secret: never returns the raw key."""
    if provider not in catalog(session):
        raise NotFoundError(f"unknown provider '{provider}'")
    settings = get_settings()
    key = effective_key(session, provider, settings)
    return {
        "name": provider,
        "configured": is_configured(provider, settings, session),
        "masked_key": _mask(key),
        "base_url": effective_base_url(session, provider, settings),
        "from_db": db_provider_key(session, provider) is not None,
    }


def set_provider_config(
    session: Session,
    provider: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Persist a provider's key and/or base_url.

    - api_key="" clears the stored key (falls back to env).
    - api_key=None leaves the stored key untouched (e.g. base_url-only update).
    - base_url="" clears the stored base_url; None leaves it untouched.
    Invalidates the settings cache so live clients pick up the change at once.
    """
    if provider not in catalog(session):
        raise NotFoundError(f"unknown provider '{provider}'")

    row = _secret_row(session, provider)
    if row is None:
        row = ProviderSecret(provider=provider, api_key="", base_url=None)

    if api_key is not None:
        row.api_key = _obfuscate(api_key) if api_key else ""
    if base_url is not None:
        row.base_url = base_url or None
    row.updated_at = utcnow()
    session.add(row)
    session.commit()

    # Drop cached Settings + provider singletons so the new key/base-url is live.
    invalidate_settings_cache()
    return get_provider_config(session, provider)


def test_connection(session: Session, provider: str) -> dict:
    """A cheap liveness check for a provider's configured key.

    Returns {ok, latency_ms, error}. Uses a short timeout and a minimal request
    (a 1-token chat / models list) so it's fast and cheap. Network/SDK errors are
    captured into `error` rather than raised, so the UI can render them inline.
    """
    if provider not in catalog(session):
        raise NotFoundError(f"unknown provider '{provider}'")
    settings = get_settings()
    if definition(provider, session)["protocol"] == "codex":
        from app.llm.connection_client import codex_status
        ok = codex_status()
        return {"ok": ok, "latency_ms": None, "error": None if ok else "Run codex login on this computer using ChatGPT, then retry."}
    key = effective_key(session, provider, settings)
    if not key:
        return {"ok": False, "latency_ms": None, "error": "no API key configured"}

    base_url = effective_base_url(session, provider, settings)
    started = time.monotonic()
    try:
        if definition(provider, session)["protocol"] == "anthropic":
            from anthropic import Anthropic

            client = Anthropic(api_key=key, base_url=base_url, timeout=10.0)
            client.messages.create(
                model=default_model(provider, settings),  # type: ignore[arg-type]
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
        elif definition(provider, session)["protocol"] == "responses":
            from openai import OpenAI
            model = default_model(provider, settings)
            if not model:
                return {"ok": False, "latency_ms": None, "error": "Set a default model on a named connection before testing Responses"}
            with OpenAI(api_key=key, base_url=base_url, timeout=10.0) as client:
                client.responses.create(model=model, input="Reply OK", max_output_tokens=64)
        else:
            from openai import OpenAI

            client = OpenAI(api_key=key, base_url=base_url, timeout=10.0)
            # models.list is the cheapest authenticated call; some gateways
            # don't implement it, so fall back to a 1-token chat completion.
            try:
                client.models.list()
            except Exception:
                client.chat.completions.create(
                    model=default_model(provider, settings),  # type: ignore[arg-type]
                    max_tokens=1,
                    messages=[{"role": "user", "content": "ping"}],
                )
        latency = int((time.monotonic() - started) * 1000)
        return {"ok": True, "latency_ms": latency, "error": None}
    except Exception as exc:  # noqa: BLE001 — surface any provider/SDK error
        latency = int((time.monotonic() - started) * 1000)
        # Never echo the SDK's raw error: a 401 body can contain a partially
        # masked key fingerprint. Map to a concise, secret-free message.
        return {
            "ok": False,
            "latency_ms": latency,
            "error": _sanitize_connection_error(exc),
        }


def suggested_models(provider: str, settings: Settings | None = None) -> list[str]:
    """Suggested model ids for a provider, with the configured default merged in.
    These are HINTS only — the user may free-type any model id."""
    settings = settings or get_settings()
    models = list(_KNOWN_MODELS.get(provider, []))
    dflt = default_model(provider, settings)  # type: ignore[arg-type]
    if dflt and dflt not in models:
        models.insert(0, dflt)
    return models


# Back-compat alias: older callers/tests used models_for().
def models_for(provider: str, settings: Settings) -> list[str]:
    return suggested_models(provider, settings)


def available_providers(
    settings: Settings | None = None, session: Session | None = None
) -> list[dict]:
    """Catalog: for each provider {name, configured, models, suggested_models,
    default_model, allow_custom, from_db}. `configured` reflects DB-or-env."""
    settings = settings or get_settings()
    out = []
    for p, entry in catalog(session).items():
        models = suggested_models(p, settings)
        out.append(
            {
                "name": p,
                "label": entry["label"],
                "protocol": entry["protocol"],
                "configured": is_configured(p, settings, session=session),
                "models": models,  # legacy field name (suggestions)
                "suggested_models": models,
                "default_model": default_model(p, settings),  # type: ignore[arg-type]
                "allow_custom": True,
                "from_db": (
                    db_provider_key(session, p) is not None
                    if session is not None
                    else False
                ),
            }
        )
    return out


# ---------------------------------------------------------------------------
# App defaults resolver.
# ---------------------------------------------------------------------------
def _config_default(key: str, settings: Settings):
    attr = APP_SETTING_DEFAULTS.get(key)
    if attr is None:
        return None
    return getattr(settings, attr, None)


def get_app_setting(
    session: Session,
    key: str,
    default=None,
    scope: str = "global",
    project_id: str | None = None,
):
    """Read a single app_settings row's value (no config fallback). Returns
    *default* if no matching row exists."""
    stmt = select(AppSetting).where(AppSetting.key == key, AppSetting.scope == scope)
    if scope == "project":
        stmt = stmt.where(AppSetting.project_id == project_id)
    row = session.exec(stmt).first()
    return row.value if row is not None else default


def set_app_setting(
    session: Session,
    key: str,
    value,
    scope: str = "global",
    project_id: str | None = None,
) -> AppSetting:
    """Upsert an app default. `scope='project'` overlays the global value for one
    project. Validates the key is known and invalidates the settings cache."""
    if key not in APP_SETTING_DEFAULTS:
        raise ValidationFailedError(f"unknown app setting key '{key}'")
    if scope not in ("global", "project"):
        raise ValidationFailedError(f"invalid scope '{scope}'")
    if scope == "project" and not project_id:
        raise ValidationFailedError("project scope requires a project_id")

    stmt = select(AppSetting).where(AppSetting.key == key, AppSetting.scope == scope)
    if scope == "project":
        stmt = stmt.where(AppSetting.project_id == project_id)
    row = session.exec(stmt).first()
    if row is None:
        row = AppSetting(key=key, scope=scope, project_id=project_id, value=value)
    else:
        row.value = value
        row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    invalidate_settings_cache()
    return row


def resolve(
    session: Session,
    key: str,
    default=None,
    project_id: str | None = None,
    settings: Settings | None = None,
):
    """The effective value of an app default, overlaying in precedence:
    project-override -> global -> config default -> *default* arg."""
    settings = settings or get_settings()
    if project_id:
        sentinel = object()
        pv = get_app_setting(
            session, key, sentinel, scope="project", project_id=project_id
        )
        if pv is not sentinel:
            return pv
    sentinel = object()
    gv = get_app_setting(session, key, sentinel, scope="global")
    if gv is not sentinel:
        return gv
    cfg = _config_default(key, settings)
    if cfg is not None:
        return cfg
    return default


def app_settings_view(
    session: Session,
    project_id: str | None = None,
    settings: Settings | None = None,
) -> dict:
    """All resolved app defaults, for GET /settings/app."""
    settings = settings or get_settings()
    return {
        k: resolve(session, k, project_id=project_id, settings=settings)
        for k in APP_SETTING_KEYS
    }


def set_app_settings(
    session: Session,
    values: dict,
    scope: str = "global",
    project_id: str | None = None,
) -> dict:
    """Bulk upsert app defaults (only known keys are written), then return the
    full resolved view."""
    for k, v in values.items():
        if k in APP_SETTING_DEFAULTS and v is not None:
            set_app_setting(session, k, v, scope=scope, project_id=project_id)
    return app_settings_view(session, project_id=project_id, settings=get_settings())


# ---------------------------------------------------------------------------
# Agent overrides (unchanged contract; model validation relaxed).
# ---------------------------------------------------------------------------
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


def _validate(
    provider: str | None,
    model: str | None,
    settings: Settings,
    session: Session | None,
) -> None:
    if provider is None and model is None:
        return  # clearing — always allowed
    if provider is None:
        raise ValidationFailedError("provider is required when setting a model")
    if provider not in catalog(session):
        raise ValidationFailedError(f"unknown provider '{provider}'")
    if not is_configured(provider, settings, session=session):
        raise ValidationFailedError(
            f"provider '{provider}' is not configured (missing API key)"
        )
    # RELAXED: any non-empty model id is accepted for a configured provider.
    # The curated lists are suggestions only — no allowlist rejection.
    if model is not None and not model.strip():
        raise ValidationFailedError("model id cannot be empty")


def set_override(
    session: Session,
    agent: str,
    provider: str | None,
    model: str | None,
    settings: Settings | None = None,
) -> dict:
    """Set or clear an agent override. Writes the DB and the in-process mirror.
    Validates the provider is configured (DB or env) and the model is non-empty.
    Nulls in both fields clear the override (revert to skill default)."""
    settings = settings or get_settings()
    if skills.get_skill(agent) is None:
        raise NotFoundError(f"unknown agent '{agent}'")
    _validate(provider, model, settings, session)

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
