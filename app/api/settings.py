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
    """Null provider+model clears the override (revert to skill default)."""

    provider: str | None = None
    model: str | None = None


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


# --------------------------------------------------------------- app defaults
@router.get("/app")
def get_app_settings(session: Session = Depends(get_session)):
    return settings_service.app_settings_view(session)


@router.put("/app")
def put_app_settings(body: AppSettingsBody, session: Session = Depends(get_session)):
    return settings_service.set_app_settings(
        session, body.model_dump(exclude_none=True)
    )
