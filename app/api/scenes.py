"""Script / scene / shot endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.database import get_session
from app.services import (
    asset_gen_service,
    op_service,
    refine_service,
    render_service,
    scene_service,
    storyboard_service,
)


def _op_response(op) -> JSONResponse:
    return JSONResponse(status_code=202, content={"op_id": op.id, "status": op.status})

router = APIRouter(tags=["scenes"])


class ScriptRequest(BaseModel):
    idea: str
    target_duration: int | None = None
    scene_count: int | None = Field(default=None, ge=1, le=20)


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
    shot_order: int | None = None


@router.post("/scripts/generate")
async def generate_script(body: ScriptRequest, session: Session = Depends(get_session)):
    script, draft = await scene_service.create_script(
        session,
        idea=body.idea,
        target_duration=body.target_duration,
        scene_count=body.scene_count,
    )
    return {"script": script, "draft": draft, "scenes": scene_service.list_scenes(session)}


@router.get("/scripts")
def list_scripts(session: Session = Depends(get_session)):
    return scene_service.list_scripts(session)


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


class ShotsGenRequest(BaseModel):
    auto_assets: bool = True


@router.post("/scenes/{scene_id}/shots/generate")
async def generate_shots(
    scene_id: str,
    body: ShotsGenRequest | None = None,
    session: Session = Depends(get_session),
):
    auto_assets = body.auto_assets if body else True
    return await scene_service.create_shots(session, scene_id, auto_assets=auto_assets)


@router.get("/scenes/{scene_id}/shots")
def list_shots(scene_id: str, session: Session = Depends(get_session)):
    return scene_service.list_shots(session, scene_id)


@router.patch("/scenes/{scene_id}")
def edit_scene(scene_id: str, body: SceneEdit, session: Session = Depends(get_session)):
    return scene_service.update_scene(session, scene_id, **body.model_dump(exclude_none=True))


@router.patch("/shots/{shot_id}")
def edit_shot(shot_id: str, body: ShotEdit, session: Session = Depends(get_session)):
    return scene_service.update_shot(session, shot_id, **body.model_dump(exclude_none=True))


@router.post("/scenes/{scene_id}/cast/{character_id}")
def add_cast(scene_id: str, character_id: str, session: Session = Depends(get_session)):
    return scene_service.add_cast_member(session, scene_id, character_id)


@router.delete("/scenes/{scene_id}/cast/{character_id}")
def remove_cast(scene_id: str, character_id: str, session: Session = Depends(get_session)):
    return scene_service.remove_cast_member(session, scene_id, character_id)


@router.post("/shots/{shot_id}/assets/{asset_id}")
def attach_asset(shot_id: str, asset_id: str, session: Session = Depends(get_session)):
    return scene_service.attach_shot_asset(session, shot_id, asset_id)


@router.delete("/shots/{shot_id}/assets/{asset_id}")
def detach_asset(shot_id: str, asset_id: str, session: Session = Depends(get_session)):
    return scene_service.detach_shot_asset(session, shot_id, asset_id)


@router.delete("/scenes/{scene_id}")
def delete_scene(scene_id: str, session: Session = Depends(get_session)):
    count = scene_service.delete_scene(session, scene_id)
    return {"deleted": scene_id, "shots_deleted": count}


@router.delete("/shots/{shot_id}")
def delete_shot(shot_id: str, session: Session = Depends(get_session)):
    scene_service.delete_shot(session, shot_id)
    return {"deleted": shot_id}


@router.post("/scenes/{scene_id}/storyboard")
async def generate_storyboard(
    scene_id: str, background: bool = False, session: Session = Depends(get_session)
):
    """Generate the scene's 分镜图 (ERNIE NxN contact sheet) from its shots.
    With ?background=true the work runs as a tracked op (202 + /ops polling)."""
    if background:
        op = op_service.start_op(
            "storyboard",
            lambda s: storyboard_service.generate_storyboard_for_scene(s, scene_id),
            scene_id=scene_id,
        )
        return _op_response(op)
    return await storyboard_service.generate_storyboard_for_scene(session, scene_id)


class AssetGenRequest(BaseModel):
    instruction: str = ""
    max_assets: int = 4


@router.post("/scenes/{scene_id}/assets/generate")
async def generate_scene_assets(
    scene_id: str,
    body: AssetGenRequest,
    background: bool = False,
    session: Session = Depends(get_session),
):
    """Plan + generate the scene's missing props/assets (ERNIE images).
    With ?background=true the work runs as a tracked op (202 + /ops polling)."""
    if background:
        op = op_service.start_op(
            "assets",
            lambda s: asset_gen_service.generate_scene_assets(
                s, scene_id, instruction=body.instruction, max_assets=body.max_assets
            ),
            scene_id=scene_id,
        )
        return _op_response(op)
    return await asset_gen_service.generate_scene_assets(
        session, scene_id, instruction=body.instruction, max_assets=body.max_assets
    )


@router.post("/scenes/{scene_id}/assets/plan")
async def plan_scene_assets(
    scene_id: str, body: AssetGenRequest, session: Session = Depends(get_session)
):
    """Plan-only suggestions: which assets the scene needs (and the shots that
    use them) without generating images or writing to the database."""
    return await asset_gen_service.plan_scene_assets(
        session, scene_id, instruction=body.instruction, max_assets=body.max_assets
    )


class RefineRequest(BaseModel):
    instruction: str


@router.post("/scenes/{scene_id}/refine")
async def refine_scene(
    scene_id: str, body: RefineRequest, session: Session = Depends(get_session)
):
    """AI-assisted edit: rewrite the scene's fields from a natural-language instruction."""
    return await refine_service.refine_scene(session, scene_id, body.instruction)


@router.post("/shots/{shot_id}/refine")
async def refine_shot(shot_id: str, body: RefineRequest, session: Session = Depends(get_session)):
    """AI-assisted edit: rewrite the shot's fields from a natural-language instruction."""
    return await refine_service.refine_shot(session, shot_id, body.instruction)


@router.post("/scenes/{scene_id}/render")
async def render_scene(scene_id: str, session: Session = Depends(get_session)):
    """Deterministic whole-scene multi-shot render (uses the 分镜图 if present)."""
    job = await render_service.render_scene(session, scene_id)
    return JSONResponse(status_code=202, content={"job_id": job.id, "status": job.status})
