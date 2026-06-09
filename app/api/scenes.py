"""Script / scene / shot endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.services import scene_service

router = APIRouter(tags=["scenes"])


class ScriptRequest(BaseModel):
    idea: str
    target_duration: int | None = None


class SceneExpandRequest(BaseModel):
    character_ids: list[str] = []


@router.post("/scripts/generate")
async def generate_script(body: ScriptRequest, session: Session = Depends(get_session)):
    draft = await scene_service.create_script(
        session, idea=body.idea, target_duration=body.target_duration
    )
    return {"draft": draft, "scenes": scene_service.list_scenes(session)}


@router.get("/scenes")
def list_scenes(session: Session = Depends(get_session)):
    return scene_service.list_scenes(session)


@router.get("/scenes/{scene_id}")
def get_scene(scene_id: str, session: Session = Depends(get_session)):
    return scene_service.get_scene(session, scene_id)


@router.post("/scenes/{scene_id}/generate")
async def expand_scene(
    scene_id: str, body: SceneExpandRequest, session: Session = Depends(get_session)
):
    return await scene_service.expand_scene(session, scene_id, body.character_ids)


@router.post("/scenes/{scene_id}/shots/generate")
async def generate_shots(scene_id: str, session: Session = Depends(get_session)):
    return await scene_service.create_shots(session, scene_id)


@router.get("/scenes/{scene_id}/shots")
def list_shots(scene_id: str, session: Session = Depends(get_session)):
    return scene_service.list_shots(session, scene_id)
