"""Script / scene / shot endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.services import render_service, scene_service, storyboard_service

router = APIRouter(tags=["scenes"])


class ScriptRequest(BaseModel):
    idea: str
    target_duration: int | None = None


class SceneExpandRequest(BaseModel):
    character_ids: list[str] = []


class SceneEdit(BaseModel):
    """Partial scene update — only supplied fields change."""

    title: str | None = None
    summary: str | None = None
    duration: int | None = None
    aspect_ratio: str | None = None
    character_ids: list[str] | None = None
    asset_ids: list[str] | None = None


class ShotEdit(BaseModel):
    """Partial shot update — only supplied fields change."""

    prompt: str | None = None
    duration: int | None = None
    camera: str | None = None
    movement: str | None = None
    asset_ids: list[str] | None = None


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


@router.patch("/scenes/{scene_id}")
def edit_scene(scene_id: str, body: SceneEdit, session: Session = Depends(get_session)):
    return scene_service.update_scene(session, scene_id, **body.model_dump(exclude_none=True))


@router.patch("/shots/{shot_id}")
def edit_shot(shot_id: str, body: ShotEdit, session: Session = Depends(get_session)):
    return scene_service.update_shot(session, shot_id, **body.model_dump(exclude_none=True))


@router.post("/scenes/{scene_id}/storyboard")
async def generate_storyboard(scene_id: str, session: Session = Depends(get_session)):
    """Generate the scene's 分镜图 (ERNIE NxN contact sheet) from its shots."""
    return await storyboard_service.generate_storyboard_for_scene(session, scene_id)


@router.post("/scenes/{scene_id}/render")
async def render_scene(scene_id: str, session: Session = Depends(get_session)):
    """Deterministic whole-scene multi-shot render (uses the 分镜图 if present)."""
    job = await render_service.render_scene(session, scene_id)
    return JSONResponse(status_code=202, content={"job_id": job.id, "status": job.status})
