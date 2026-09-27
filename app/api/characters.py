"""Character endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.services import character_service

router = APIRouter(prefix="/characters", tags=["characters"])


class CreateCharacter(BaseModel):
    name: str
    description: str = ""


class UpdateCharacter(BaseModel):
    """Partial update — only provided fields are applied."""

    name: str | None = None
    description: str | None = None
    appearance: str | None = None
    personality: str | None = None
    visual_rules: list[str] | None = None
    voice_rules: list[str] | None = None
    sample_dialogue: str | None = None


class BibleRequest(BaseModel):
    notes: str


class ReferenceSheetRequest(BaseModel):
    angles: list[str] | None = None


@router.post("")
def create_character(body: CreateCharacter, session: Session = Depends(get_session)):
    return character_service.create_character(
        session, name=body.name, description=body.description
    )


@router.get("")
def list_characters(session: Session = Depends(get_session)):
    return character_service.list_characters(session)


@router.get("/{character_id}")
def get_character(character_id: str, session: Session = Depends(get_session)):
    return character_service.get_character(session, character_id)


@router.patch("/{character_id}")
def update_character(
    character_id: str,
    body: UpdateCharacter,
    session: Session = Depends(get_session),
):
    return character_service.update_character(
        session,
        character_id,
        name=body.name,
        description=body.description,
        appearance=body.appearance,
        personality=body.personality,
        visual_rules=body.visual_rules,
        voice_rules=body.voice_rules,
        sample_dialogue=body.sample_dialogue,
    )


@router.delete("/{character_id}")
def delete_character(character_id: str, session: Session = Depends(get_session)):
    detached = character_service.delete_character(session, character_id)
    return {"deleted": character_id, "detached_from": detached}


@router.post("/{character_id}/bible")
async def generate_bible(
    character_id: str, body: BibleRequest, session: Session = Depends(get_session)
):
    return await character_service.generate_bible(session, character_id, body.notes)


@router.post("/{character_id}/reference-sheets")
async def generate_reference_sheets(
    character_id: str,
    body: ReferenceSheetRequest,
    session: Session = Depends(get_session),
):
    return await character_service.generate_reference_sheets(
        session, character_id, angles=body.angles
    )
