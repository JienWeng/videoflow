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
from string import Formatter

from sqlmodel import Session, select

from app.config import Settings, get_settings, invalidate_settings_cache
from app.errors import NotFoundError, ValidationFailedError
from app.llm import prompts, skills
from app.llm.providers import ProviderName, default_model
from app.models.base import utcnow
from app.models.setting import AgentSetting, AppSetting, ProviderSecret

# Curated, short "suggested options" per provider. These are hints for the UI
# only — the user may free-type any model id for a configured provider. The
# provider's configured default model is always merged in.
_KNOWN_MODELS: dict[str, list[str]] = {
    "minimax": ["MiniMax-Text-01", "MiniMax-M2"],
    "openai": ["gpt-4o-mini", "gpt-4o"],
    "anthropic": ["claude-sonnet-4-6", "claude-opus-4-8"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro"],
    "atlas": ["qwen/qwen3-vl-30b-a3b-instruct", "glm-5v"],
}

# All providers the UI knows about (order is display order).
PROVIDERS: list[ProviderName] = ["minimax", "openai", "anthropic", "gemini", "atlas"]


# ---------------------------------------------------------------------------
# App-default keys: name -> Settings attribute holding the config default.
# The resolver overlays app_settings rows on top of these config defaults.
# ---------------------------------------------------------------------------
APP_SETTING_DEFAULTS: dict[str, str] = {
    "default_aspect_ratio": "default_aspect_ratio",
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
    # Autonomous director: supervision thresholds, feature flags, budget.
    "qa_accept_score": "qa_accept_score",
    "qa_min_dimension": "qa_min_dimension",
    "qa_revise_floor": "qa_revise_floor",
    "qa_max_attempts": "qa_max_attempts",
    "qa_min_improvement": "qa_min_improvement",
    "qa_max_frames": "qa_max_frames",
    "supervision_enabled": "supervision_enabled",
    "precheck_enabled": "precheck_enabled",
    "storyboard_judge_enabled": "storyboard_judge_enabled",
    "storyboard_best_of": "storyboard_best_of",
    "targeted_revise_enabled": "targeted_revise_enabled",
    "run_budget_units": "run_budget_units",
    "cost_unit_text": "cost_unit_text",
    "cost_unit_vision": "cost_unit_vision",
    "cost_unit_image": "cost_unit_image",
    "cost_unit_video_per_second": "cost_unit_video_per_second",
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
    }[provider]


def _env_base_url(provider: str, settings: Settings) -> str | None:
    return {
        "minimax": settings.minimax_base_url,
        "openai": settings.openai_base_url,
        "anthropic": None,  # anthropic SDK uses its own default base url
        "gemini": settings.gemini_base_url,
        # The LLM (chat) endpoint, NOT the image/video gateway.
        "atlas": settings.atlas_llm_base_url,
    }[provider]


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
    return _env_base_url(provider, settings)


def is_configured(
    provider: str,
    settings: Settings | None = None,
    session: Session | None = None,
) -> bool:
    """True if *provider* has a usable API key — from the DB OR the environment."""
    settings = settings or get_settings()
    return bool(effective_key(session, provider, settings))


def get_provider_config(session: Session, provider: str) -> dict:
    """The UI view of a provider's secret: never returns the raw key."""
    if provider not in PROVIDERS:
        raise NotFoundError(f"unknown provider '{provider}'")
    settings = get_settings()
    key = effective_key(session, provider, settings)
    return {
        "name": provider,
        "configured": bool(key),
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
    if provider not in PROVIDERS:
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
    if provider not in PROVIDERS:
        raise NotFoundError(f"unknown provider '{provider}'")
    settings = get_settings()
    key = effective_key(session, provider, settings)
    if not key:
        return {"ok": False, "latency_ms": None, "error": "no API key configured"}

    base_url = effective_base_url(session, provider, settings)
    started = time.monotonic()
    try:
        if provider == "anthropic":
            from anthropic import Anthropic

            client = Anthropic(api_key=key, timeout=10.0)
            client.messages.create(
                model=default_model(provider, settings),  # type: ignore[arg-type]
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
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
    for p in PROVIDERS:
        models = suggested_models(p, settings)
        out.append(
            {
                "name": p,
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
# Agent overrides + Agent Studio (prompt / tuning / context customization).
# ---------------------------------------------------------------------------
def get_overrides(session: Session) -> dict[str, dict[str, str | None]]:
    """Provider/model overrides keyed by agent (back-compat shape). An agent
    appears here whenever it has ANY persisted customization row."""
    rows = session.exec(select(AgentSetting)).all()
    return {r.agent: {"provider": r.provider, "model": r.model} for r in rows}


def load_overrides(session: Session) -> None:
    """Rebuild the in-process mirror from the DB (called at startup and after
    every write) — carries routing AND studio customization."""
    skills.clear_overrides()
    for row in session.exec(select(AgentSetting)).all():
        skills.set_record(
            row.agent,
            provider=row.provider,
            model=row.model,
            system_prompt=row.system_prompt,
            temperature=row.temperature,
            max_retries=row.max_retries,
            context_excludes=row.context_excludes,
        )


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
    if provider not in PROVIDERS:
        raise ValidationFailedError(f"unknown provider '{provider}'")
    if not is_configured(provider, settings, session=session):
        raise ValidationFailedError(
            f"provider '{provider}' is not configured (missing API key)"
        )
    # RELAXED: any non-empty model id is accepted for a configured provider.
    # The curated lists are suggestions only — no allowlist rejection.
    if model is not None and not model.strip():
        raise ValidationFailedError("model id cannot be empty")


def _scan_fields(text: str) -> set[str]:
    """Every `{field}` reference in a format template, INCLUDING auto/positional
    (`{}` / `{0}` -> reported as '') and fields nested inside format specs
    (`{x:>{y}}` -> x and y). Raises ValueError on malformed braces. Escaped
    `{{ }}` yields nothing (literal text)."""
    found: set[str] = set()
    for _, name, spec, _ in Formatter().parse(text):
        if name is not None:
            found.add(name.split(".")[0].split("[")[0])
        if spec:
            found |= _scan_fields(spec)
    return found


def _validate_prompt(agent: str, text: str) -> None:
    """A prompt override may not introduce `{placeholders}` the agent can't fill
    (the default carries none) and may not contain malformed braces — either
    would silently break str.format at call time. Escaped `{{ }}` is fine."""
    allowed = prompts.extract_placeholders(skills.get_skill(agent).system_prompt)
    try:
        used = _scan_fields(text)
    except (ValueError, IndexError) as exc:
        raise ValidationFailedError(
            "the prompt has unbalanced or invalid { } braces "
            "(use {{ }} for literal braces)"
        ) from exc
    # '' marks an auto/positional field ({} or {0}) — always rejected.
    unknown = used - allowed
    if unknown:
        shown = sorted(k if k else "{}" for k in unknown)
        allowed_str = ", ".join(sorted(allowed)) or "no placeholders"
        raise ValidationFailedError(
            f"unknown placeholder(s) {shown} — this agent provides "
            f"{allowed_str}. Write rules as plain text; context is supplied "
            "automatically."
        )


def _validate_context_excludes(agent: str, excludes: list[str]) -> None:
    optional = {s.key for s in skills.context_sources(agent) if not s.required}
    invalid = [k for k in excludes if k not in optional]
    if invalid:
        raise ValidationFailedError(
            f"cannot disable context {invalid} for {agent}: not an optional "
            f"context source (optional: {sorted(optional) or 'none'})"
        )


def _upsert(session: Session, agent: str, **changes) -> None:
    """Apply only the supplied columns to the agent's row; delete the row when
    every override field is empty (so a cleared override reverts to defaults)."""
    row = session.exec(select(AgentSetting).where(AgentSetting.agent == agent)).first()
    existed = row is not None
    if row is None:
        row = AgentSetting(agent=agent)
    for k, v in changes.items():
        setattr(row, k, v)
    empty = (
        not row.provider
        and not row.model
        and not row.system_prompt
        and row.temperature is None
        and row.max_retries is None
        and not row.context_excludes
    )
    if empty:
        if existed:
            session.delete(row)
            session.commit()
        return
    row.updated_at = utcnow()
    session.add(row)
    session.commit()


def set_override(
    session: Session,
    agent: str,
    provider: str | None,
    model: str | None,
    settings: Settings | None = None,
) -> dict:
    """Set or clear an agent's provider/model routing. Validates the provider is
    configured (DB or env) and the model is non-empty. Nulls in both fields clear
    the routing override; any prompt/tuning customization on the agent is kept."""
    settings = settings or get_settings()
    if skills.get_skill(agent) is None:
        raise NotFoundError(f"unknown agent '{agent}'")
    _validate(provider, model, settings, session)
    _upsert(session, agent, provider=provider, model=model)
    load_overrides(session)
    return agent_view(agent, settings)


def set_customization(
    session: Session,
    agent: str,
    *,
    system_prompt: str | None = None,
    temperature: float | None = None,
    max_retries: int | None = None,
    context_excludes: list[str] | None = None,
    settings: Settings | None = None,
) -> dict:
    """Set the agent's studio customization (prompt / temperature / max_retries /
    context excludes). REPLACE semantics: each unset field reverts to the code
    default, so the UI sends the complete intended state. Routing (provider/
    model) is untouched. Validates the prompt and context keys."""
    settings = settings or get_settings()
    if skills.get_skill(agent) is None:
        raise NotFoundError(f"unknown agent '{agent}'")
    sp = system_prompt or None  # "" => clear (use default)
    if sp is not None:
        _validate_prompt(agent, sp)
    temp = None if temperature is None else max(0.0, min(2.0, float(temperature)))
    retries = None if max_retries is None else max(0, min(5, int(max_retries)))
    excl: list[str] | None = None
    if context_excludes:
        _validate_context_excludes(agent, context_excludes)
        excl = list(dict.fromkeys(context_excludes))  # de-dupe, keep order
    _upsert(
        session,
        agent,
        system_prompt=sp,
        temperature=temp,
        max_retries=retries,
        context_excludes=excl,
    )
    load_overrides(session)
    return agent_detail(session, agent, settings)


def reset_agent(
    session: Session, agent: str, settings: Settings | None = None
) -> dict:
    """Clear ALL customization (routing + studio) for one agent."""
    settings = settings or get_settings()
    if skills.get_skill(agent) is None:
        raise NotFoundError(f"unknown agent '{agent}'")
    row = session.exec(select(AgentSetting).where(AgentSetting.agent == agent)).first()
    if row is not None:
        session.delete(row)
        session.commit()
    load_overrides(session)
    return agent_detail(session, agent, settings)


def agent_view(agent: str, settings: Settings | None = None) -> dict:
    """The effective + default routing for one agent, for the API/UI list."""
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
        "customized": skills.is_customized(agent),
    }


def agent_detail(
    session: Session, agent: str, settings: Settings | None = None
) -> dict:
    """Full studio view for one agent: routing + prompt (override & default) +
    tuning (override & default) + togglable context sources with current state."""
    settings = settings or get_settings()
    base = skills.get_skill(agent)
    if base is None:
        raise NotFoundError(f"unknown agent '{agent}'")
    load_overrides(session)
    row = session.exec(select(AgentSetting).where(AgentSetting.agent == agent)).first()
    excludes = skills.context_excludes(agent)
    sources = [
        {
            "key": s.key,
            "label": s.label,
            "required": s.required,
            "enabled": s.required or s.key not in excludes,
        }
        for s in skills.context_sources(agent)
    ]
    return {
        **agent_view(agent, settings),
        "system_prompt": row.system_prompt if row else None,
        "default_prompt": base.system_prompt,
        "required_placeholders": sorted(
            prompts.extract_placeholders(base.system_prompt)
        ),
        "temperature": row.temperature if row else None,
        "default_temperature": base.temperature,
        "max_retries": row.max_retries if row else None,
        "default_max_retries": base.max_retries,
        "context_sources": sources,
    }


def all_agents(session: Session, settings: Settings | None = None) -> list[dict]:
    settings = settings or get_settings()
    load_overrides(session)
    return [agent_view(a, settings) for a in skills.SKILLS]
