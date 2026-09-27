"""Settings endpoints.

Agents:
  GET /settings/agents       → every agent with its effective + default routing.
  PUT /settings/agents/{a}   → set/clear an override (422 on unconfigured).

Providers (keys/base-urls, persisted in the DB, prefer over .env when set):
  GET  /settings/providers          → catalog (configured DB-or-env + suggestions).
  GET  /settings/providers/{name}   → one provider's config (masked key, base_url).
  PUT  /settings/providers/{name}   → set api_key and/or base_url (never echoes key).
  POST /settings/providers/{name}/test → cheap liveness check {ok, latency_ms, error}.

App defaults (overridable, take effect without a restart):
  GET /settings/app  → resolved app defaults (aspect ratio, caption style, models…).
  PUT /settings/app  → upsert global app defaults; returns the resolved view.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
from urllib.parse import urlparse
from sqlmodel import Session

from app.database import get_session
from app.services import settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


class ConnectionBody(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    preset: str
    protocol: Literal["chat", "responses", "anthropic", "codex"]
    base_url: str | None = None
    model: str = Field(default="", max_length=200)
    mode: Literal["auto", "tools", "json", "prompt"] = "auto"
    vision: bool = True


@router.get("/connection-presets")
def connection_presets():
    from app.llm.connections import catalog
    return catalog()


@router.post("/connections", status_code=201)
def create_connection(body: ConnectionBody, session: Session = Depends(get_session)):
    from app.llm.connections import PRESETS
    from app.models.setting import Connection
    from uuid import uuid4
    if body.preset not in PRESETS:
        raise HTTPException(422, "Unknown preset")
    url = body.base_url or PRESETS[body.preset].url
    if body.protocol != "codex":
        parsed = urlparse(url or "")
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise HTTPException(422, "Supply an HTTP(S) base URL without credentials, query, or fragment")
    name = "conn_" + uuid4().hex
    row = Connection(name=name, **{**body.model_dump(), "base_url": url})
    session.add(row)
    session.commit()
    return {"name": name}


class AgentOverride(BaseModel):
    """Null provider+model clears the override (revert to skill default)."""

    provider: str | None = None
    model: str | None = None


class ProviderConfig(BaseModel):
    """Set a provider's key and/or base url. api_key="" clears the stored key;
    a null field is left untouched (e.g. update base_url only)."""

    api_key: str | None = None
    base_url: str | None = None


class VerifyModelBody(BaseModel):
    model: str = Field(min_length=1, max_length=200)


@router.post("/providers/{name}/verify-model")
async def verify_model(name: str, body: VerifyModelBody, session: Session = Depends(get_session)):
    from app.llm.connections import catalog
    from app.llm.structured_client import StructuredLLMClient
    from app.config import get_settings
    if name not in catalog(session):
        raise HTTPException(404, "Unknown connection")
    class Probe(BaseModel):
        answer: Literal["ok"]
    try:
        await StructuredLLMClient(get_settings()).generate(provider=name, model=body.model,
            response_model=Probe, user_prompt='Return {"answer":"ok"}', timeout_s=60, max_retries=1)
        return {"ok": True, "error": None}
    except Exception:
        return {"ok": False, "error": "Model/JSON test failed. Check credentials, model access, protocol, output mode, and usage limits."}


class AppSettingsBody(BaseModel):
    """Partial upsert of app defaults — only supplied (non-null) keys change."""

    default_aspect_ratio: str | None = None
    default_video_provider: Literal["atlascloud", "openrouter"] | None = None
    default_image_provider: Literal["atlascloud", "openrouter"] | None = None
    default_scene_duration: float | None = None
    caption_style: str | None = None
    caption_language: str | None = None
    whisper_model: str | None = None
    dialogue_language: str | None = None
    image_model: str | None = None
    ref_image_model: str | None = None
    video_model: str | None = None
    vl_model: str | None = None
    max_video_refs: int | None = Field(default=None, ge=1)
    render_negatives: list[str] | None = None


# ----------------------------------------------------------------- agents
@router.get("/agents")
def list_agents(session: Session = Depends(get_session)):
    return settings_service.all_agents(session)


@router.put("/agents/{agent}")
def set_agent(
    agent: str, body: AgentOverride, session: Session = Depends(get_session)
):
    return settings_service.set_override(session, agent, body.provider, body.model)


# --------------------------------------------------------------- providers
@router.get("/providers")
def list_providers(session: Session = Depends(get_session)):
    return settings_service.available_providers(session=session)


@router.get("/providers/{name}")
def get_provider(name: str, session: Session = Depends(get_session)):
    return settings_service.get_provider_config(session, name)


@router.put("/providers/{name}")
def set_provider(
    name: str, body: ProviderConfig, session: Session = Depends(get_session)
):
    return settings_service.set_provider_config(
        session, name, api_key=body.api_key, base_url=body.base_url
    )


@router.post("/providers/{name}/test")
def test_provider(name: str, session: Session = Depends(get_session)):
    return settings_service.test_connection(session, name)


@router.get("/providers/{name}/models")
def discover_models(name: str, session: Session = Depends(get_session)):
    from app.llm.connections import definition, catalog
    from app.config import get_settings
    if name not in catalog(session):
        raise HTTPException(404, "Unknown connection")
    if definition(name, session)["protocol"] == "codex":
        return {"models": [], "error": "Codex model discovery is not available here; enter a model available to your ChatGPT account."}
    settings = get_settings()
    key = settings_service.effective_key(session, name, settings)
    url = settings_service.effective_base_url(session, name, settings)
    if not key:
        raise HTTPException(422, "Configure credentials first")
    try:
        if definition(name, session)["protocol"] == "anthropic":
            from anthropic import Anthropic
            with Anthropic(api_key=key, base_url=url, timeout=10) as client:
                models = client.models.list().data
        else:
            from openai import OpenAI
            with OpenAI(api_key=key, base_url=url, timeout=10) as client:
                models = client.models.list().data
        return {"models": sorted({m.id for m in models}), "error": None}
    except Exception:
        return {"models": [], "error": "Model discovery unavailable. Enter your provider's model ID manually."}


# --------------------------------------------------------------- app defaults
@router.get("/app")
def get_app_settings(session: Session = Depends(get_session)):
    return settings_service.app_settings_view(session)


@router.put("/app")
def put_app_settings(body: AppSettingsBody, session: Session = Depends(get_session)):
    return settings_service.set_app_settings(
        session, body.model_dump(exclude_none=True)
    )
