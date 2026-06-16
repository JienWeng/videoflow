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

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.services import settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


class AgentOverride(BaseModel):
    """Null provider+model clears the routing override (revert to skill default)."""

    provider: str | None = None
    model: str | None = None


class AgentCustomization(BaseModel):
    """Agent Studio customization. REPLACE semantics — send the complete intended
    state; an unset (null/empty) field reverts to the code default for that field.
    Routing (provider/model) is set separately via PUT /settings/agents/{a}."""

    system_prompt: str | None = None
    temperature: float | None = None
    max_retries: int | None = None
    context_excludes: list[str] | None = None


class ProviderConfig(BaseModel):
    """Set a provider's key and/or base url. api_key="" clears the stored key;
    a null field is left untouched (e.g. update base_url only)."""

    api_key: str | None = None
    base_url: str | None = None


class AppSettingsBody(BaseModel):
    """Partial upsert of app defaults — only supplied (non-null) keys change."""

    default_aspect_ratio: str | None = None
    default_scene_duration: float | None = None
    caption_style: str | None = None
    caption_language: str | None = None
    whisper_model: str | None = None
    dialogue_language: str | None = None
    image_model: str | None = None
    ref_image_model: str | None = None
    video_model: str | None = None
    vl_model: str | None = None
    max_video_refs: int | None = None
    render_negatives: list[str] | None = None


# ----------------------------------------------------------------- agents
@router.get("/agents")
def list_agents(session: Session = Depends(get_session)):
    return settings_service.all_agents(session)


@router.get("/agents/{agent}")
def get_agent(agent: str, session: Session = Depends(get_session)):
    return settings_service.agent_detail(session, agent)


@router.put("/agents/{agent}")
def set_agent(
    agent: str, body: AgentOverride, session: Session = Depends(get_session)
):
    return settings_service.set_override(session, agent, body.provider, body.model)


@router.put("/agents/{agent}/customization")
def set_agent_customization(
    agent: str, body: AgentCustomization, session: Session = Depends(get_session)
):
    return settings_service.set_customization(
        session,
        agent,
        system_prompt=body.system_prompt,
        temperature=body.temperature,
        max_retries=body.max_retries,
        context_excludes=body.context_excludes,
    )


@router.post("/agents/{agent}/reset")
def reset_agent(agent: str, session: Session = Depends(get_session)):
    return settings_service.reset_agent(session, agent)


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


# --------------------------------------------------------------- app defaults
@router.get("/app")
def get_app_settings(session: Session = Depends(get_session)):
    return settings_service.app_settings_view(session)


@router.put("/app")
def put_app_settings(body: AppSettingsBody, session: Session = Depends(get_session)):
    return settings_service.set_app_settings(
        session, body.model_dump(exclude_none=True)
    )
