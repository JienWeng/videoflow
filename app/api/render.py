"""Render endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlmodel import Session

from app.agents.prompt_agent import build_render_spec
from app.database import get_session
from app.errors import NotFoundError
from app.models import Asset, Character, RenderOutput, Shot
from app.schemas import RenderSpec, ShotSpec
from app.services import render_service, scene_service, style_service

logger = logging.getLogger(__name__)

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

    # Tolerance / self-healing: drop stored asset ids without an Asset row
    # (e.g. hallucinated ids persisted by older agent runs) — a missing prop
    # must never 404 a whole render.
    shot_asset_ids = []
    for aid in shot_row.asset_ids_json or []:
        if session.get(Asset, aid) is not None:
            shot_asset_ids.append(aid)
        else:
            logger.warning(
                "skipping unknown asset id %s while rendering shot %s", aid, shot_row.id
            )
    shot = ShotSpec(
        shot_id=shot_row.id,
        duration=shot_row.duration,
        prompt=shot_row.prompt,
        camera=shot_row.camera,
        movement=shot_row.movement,
        asset_ids=shot_asset_ids,
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
        story=scene_service.story_context(session, scene),
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
    output_id: str,
    body: CaptionRequest,
    background: bool = False,
    session: Session = Depends(get_session),
):
    """Auto-captions: transcribe the Kling voice track (faster-whisper) and burn
    styled subtitles into a copy of the video. With ?background=true the work
    runs as a tracked op (202 + /ops polling)."""
    from app.services import caption_service, op_service

    if background:
        op = op_service.start_op(
            "caption",
            lambda s: caption_service.caption_output(
                s, output_id, style=body.style, language=body.language, model=body.model
            ),
            output_id=output_id,
        )
        return JSONResponse(status_code=202, content={"op_id": op.id, "status": op.status})
    return await caption_service.caption_output(
        session, output_id, style=body.style, language=body.language, model=body.model
    )


class CaptionLine(BaseModel):
    start: float
    end: float
    text: str


class CaptionUpdateRequest(BaseModel):
    segments: list[CaptionLine]
    style: str | None = None  # None -> keep the style from the last caption run


@router.get("/outputs/{output_id}/captions")
def get_captions(output_id: str, session: Session = Depends(get_session)):
    """Stored caption segments for the editor. `available=False` (with empty
    segments) when the output was never captioned."""
    output = session.get(RenderOutput, output_id)
    if output is None:
        raise NotFoundError(f"render output {output_id} not found")
    data = output.captions_json or {}
    segments = data.get("segments") or []
    return {"segments": segments, "style": data.get("style"), "available": bool(segments)}


@router.put("/outputs/{output_id}/captions")
async def update_captions(
    output_id: str,
    body: CaptionUpdateRequest,
    background: bool = False,
    session: Session = Depends(get_session),
):
    """Replace the caption segments and re-burn the subtitles (no whisper).
    With ?background=true the burn runs as a tracked op (202 + /ops polling)."""
    from app.services import caption_service, op_service

    segments = [s.model_dump() for s in body.segments]
    if background:
        op = op_service.start_op(
            "caption",
            lambda s: caption_service.recaption_output(
                s, output_id, segments, style=body.style
            ),
            output_id=output_id,
        )
        return JSONResponse(status_code=202, content={"op_id": op.id, "status": op.status})
    return await caption_service.recaption_output(
        session, output_id, segments, style=body.style
    )


@router.get("/caption-styles")
def caption_styles():
    from app.services.caption_service import STYLES

    return list(STYLES)


@router.get("/caption-config")
def caption_config(session: Session = Depends(get_session)):
    from app.config import get_settings
    from app.services.caption_service import STYLES, WHISPER_MODELS, default_caption_style

    return {
        "styles": list(STYLES),
        "models": WHISPER_MODELS,
        "default_model": get_settings().whisper_model,
        "default_language": "zh",
        "default_style": default_caption_style(style_service.get_style(session)),
    }


@router.get("/outputs/{output_id}/editor")
def get_editor_data(output_id: str, session: Session = Depends(get_session)):
    """Return everything the video-editor page needs in a single call:
    the output row, captions, shot timeline blocks, and scene metadata."""
    from app.models.render_job import RenderJob
    from app.models.scene import Scene

    output = session.get(RenderOutput, output_id)
    if output is None:
        raise NotFoundError(f"render output {output_id} not found")

    # --- Output block ---
    qa_issues: list = []
    if output.qa_json:
        qa_issues = output.qa_json.get("issues") or []
    output_block = {
        "id": output.id,
        "video_path": output.video_path,
        "captioned_path": output.captioned_path,
        "thumbnail_path": output.thumbnail_path,
        "score": output.score,
        "qa_issues": qa_issues,
    }

    # --- Captions block (same logic as GET /captions) ---
    cap_data = output.captions_json or {}
    cap_segments = cap_data.get("segments") or []
    captions_block = {
        "segments": cap_segments,
        "style": cap_data.get("style"),
        "available": bool(cap_segments),
    }

    # --- Scene + Shot blocks ---
    job = session.get(RenderJob, output.render_job_id)
    spec: dict = {}
    if job and job.request_json:
        spec = job.request_json.get("spec") or {}

    scene_block = None
    shots_block: list = []
    total_duration: float = 0.0

    if not spec:
        # Legacy job with no spec stored.
        return {
            "output": output_block,
            "captions": captions_block,
            "shots": shots_block,
            "scene": scene_block,
            "total_duration": total_duration,
        }

    # Resolve scene.
    scene_id = spec.get("scene_id") or (job.scene_id if job else None)
    scene: Scene | None = None
    if scene_id:
        scene = session.get(Scene, scene_id)
    if scene:
        scene_block = {"id": scene.id, "title": scene.title}

    multi_prompt: list[dict] = spec.get("multi_prompt") or []
    spec_duration: int = spec.get("duration") or 0

    if not multi_prompt:
        # Single-prompt render: one block spanning total duration.
        total_duration = float(spec_duration)
        shots_block = [
            {
                "index": 1,
                "start": 0.0,
                "end": total_duration,
                "duration": spec_duration,
                "prompt": spec.get("prompt") or "",
                "shot_id": None,
                "camera": None,
                "movement": None,
            }
        ]
    else:
        # Multi-prompt: build cumulative time blocks and match to live Shot rows.
        from app.services.scene_service import list_shots

        live_shots = list_shots(session, scene.id) if scene else []

        cursor = 0.0
        for i, entry in enumerate(multi_prompt):
            dur = entry.get("duration") or 0
            start = cursor
            end = cursor + dur
            # Match by position (0-based index i -> shot at order i).
            matched_shot = live_shots[i] if i < len(live_shots) else None
            shots_block.append(
                {
                    "index": entry.get("index") or (i + 1),
                    "start": start,
                    "end": end,
                    "duration": dur,
                    "prompt": entry.get("prompt") or "",
                    "shot_id": matched_shot.id if matched_shot else None,
                    "camera": matched_shot.camera if matched_shot else None,
                    "movement": matched_shot.movement if matched_shot else None,
                }
            )
            cursor = end
        total_duration = cursor

    return {
        "output": output_block,
        "captions": captions_block,
        "shots": shots_block,
        "scene": scene_block,
        "total_duration": total_duration,
    }


@router.get("/render-jobs")
def list_jobs(session: Session = Depends(get_session)):
    return render_service.list_jobs(session)


@router.get("/render-jobs/{job_id}")
def get_job(job_id: str, session: Session = Depends(get_session)):
    job = render_service.get_job(session, job_id)
    return {"job": job, "outputs": render_service.job_outputs(session, job_id)}
