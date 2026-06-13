"""Settings endpoints — per-agent LLM provider/model selection.

GET /settings/agents     → every agent with its effective + default routing.
GET /settings/providers  → the catalog (which providers are configured + models).
PUT /settings/agents/{a} → set/clear an override (422 on unconfigured/unknown).
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


@router.get("/agents")
def list_agents(session: Session = Depends(get_session)):
    return settings_service.all_agents(session)


@router.get("/providers")
def list_providers():
    return settings_service.available_providers()


@router.put("/agents/{agent}")
def set_agent(
    agent: str, body: AgentOverride, session: Session = Depends(get_session)
):
    return settings_service.set_override(session, agent, body.provider, body.model)
