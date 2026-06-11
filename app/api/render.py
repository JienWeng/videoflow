"""Render endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlmodel import Session

from app.agents.prompt_agent import build_render_spec
from app.database import get_session
from app.errors import NotFoundError
from app.models import Asset, Character, Shot
from app.schemas import RenderSpec, ShotSpec
from app.services import render_service, scene_service, style_service

router = APIRouter(tags=["render"])


class NamedRef(BaseModel):
    name: str
    asset_id: str


class RenderFromShotRequest(BaseModel):
    scene_id: str
    shot_id: str
    named_references: list[NamedRef] = []
    character_ids: list[str] = []
    video_asset_id: str | None = None
    aspect_ratio: str | None = None  # falls back to DEFAULT_ASPECT_RATIO (9:16)


def _job_response(job) -> JSONResponse:
    return JSONResponse(status_code=202, content={"job_id": job.id, "status": job.status})


@router.post("/render")
async def render(spec: RenderSpec, session: Session = Depends(get_session)):
    """Submit a fully-formed RenderSpec (deterministic path)."""
    job = await render_service.start_render(session, spec)
    return _job_response(job)


@router.post("/render/from-shot")
async def render_from_shot(
    body: RenderFromShotRequest, session: Session = Depends(get_session)
):
    """Run the prompt agent to assemble a RenderSpec from a stored shot, then render."""
    scene = scene_service.get_scene(session, body.scene_id)
    shot_row = session.get(Shot, body.shot_id)
    if shot_row is None:
        raise NotFoundError(f"shot {body.shot_id} not found")

    shot = ShotSpec(
        shot_id=shot_row.id,
        duration=shot_row.duration,
        prompt=shot_row.prompt,
        camera=shot_row.camera,
        movement=shot_row.movement,
        asset_ids=list(shot_row.asset_ids_json or []),
    )
    # Characters: explicit ids win, otherwise fall back to the scene's cast so
    # their reference images always reach Kling images[].
    character_ids = body.character_ids or list(scene.character_ids_json or [])
    bibles = [
        scene_service.character_to_bible(c)
        for cid in character_ids
        if (c := session.get(Character, cid))
    ]
    asset_names = {
        aid: a.name
        for aid in shot.asset_ids
        if (a := session.get(Asset, aid)) and a.name
    }
    spec = await build_render_spec(
        scene_id=scene.id,
        scene_summary=scene.summary,
        shot=shot,
        aspect_ratio=body.aspect_ratio,
        named_references=[r.model_dump() for r in body.named_references],
        character_bibles=bibles,
        asset_names=asset_names,
        video_asset_id=body.video_asset_id,
        style=style_service.style_context(style_service.get_style(session)),
    )
    job = await render_service.start_render(session, spec)
    return _job_response(job)


@router.post("/outputs/{output_id}/retry")
async def retry_output(output_id: str, session: Session = Depends(get_session)):
    """Corrective re-render: resubmit the output's original RenderSpec with the
    QA issues folded into the prompt. Manual trigger only."""
    job = await render_service.retry_output(session, output_id)
    return _job_response(job)


class CaptionRequest(BaseModel):
    style: str = "kids"
    language: str | None = "zh"  # None -> auto-detect
    model: str | None = None     # None -> settings.whisper_model


@router.post("/outputs/{output_id}/caption")
async def caption_output(
    output_id: str, body: CaptionRequest, session: Session = Depends(get_session)
):
    """Auto-captions: transcribe the Kling voice track (faster-whisper) and burn
    styled subtitles into a copy of the video."""
    from app.services import caption_service

    return await caption_service.caption_output(
        session, output_id, style=body.style, language=body.language, model=body.model
    )


@router.get("/caption-styles")
def caption_styles():
    from app.services.caption_service import STYLES

    return list(STYLES)


@router.get("/caption-config")
def caption_config():
    from app.config import get_settings
    from app.services.caption_service import STYLES, WHISPER_MODELS

    return {
        "styles": list(STYLES),
        "models": WHISPER_MODELS,
        "default_model": get_settings().whisper_model,
        "default_language": "zh",
    }


@router.get("/render-jobs")
def list_jobs(session: Session = Depends(get_session)):
    return render_service.list_jobs(session)


@router.get("/render-jobs/{job_id}")
def get_job(job_id: str, session: Session = Depends(get_session)):
    job = render_service.get_job(session, job_id)
    return {"job": job, "outputs": render_service.job_outputs(session, job_id)}
