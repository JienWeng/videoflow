"""Project StyleGuide endpoints — singleton style record."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.services import style_service

router = APIRouter(tags=["style"])


class StyleEdit(BaseModel):
    """Partial style update — only supplied fields change."""

    name: str | None = None
    style_prompt: str | None = None
    palette: str | None = None
    lighting: str | None = None
    audience: str | None = None
    tone: str | None = None
    reference_asset_ids: list[str] | None = None


@router.get("/style")
def get_style(session: Session = Depends(get_session)):
    return style_service.get_style(session)


@router.patch("/style")
def edit_style(body: StyleEdit, session: Session = Depends(get_session)):
    return style_service.upsert_style(session, **body.model_dump())


@router.post("/style/ingest")
async def ingest_style(session: Session = Depends(get_session)):
    """Derive the project style guide from the story's scenes/characters/assets."""
    return await style_service.ingest_style(session)
