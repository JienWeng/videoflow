"""Simple user-facing video generation endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Literal
from sqlmodel import Session

from app.database import get_session
from app.services import op_service, video_generation_service, video_preflight_service
from app.services import project_service

router = APIRouter(tags=["videos"])


@router.get("/videos/preflight")
def video_preflight(
    aspect_ratio: str = Query(default="9:16"),
    style: str = Query(default="2d-picture-book"),
    session: Session = Depends(get_session),
):
    return video_preflight_service.video_preflight(
        session, aspect_ratio=aspect_ratio, style_choice=style
    )


class VideoGenerateRequest(BaseModel):
    idea: str = Field(min_length=1, max_length=8000)
    target_duration: int | None = Field(default=None, ge=3, le=300)
    scene_count: int | None = Field(default=None, ge=1, le=20)
    style: str = "2d-picture-book"
    aspect_ratio: str = "9:16"
    language: str = "English"
    conversation_mode: Literal["dialogue"] = "dialogue"
    instruction: str = Field(default="", max_length=500)


def _op_response(op) -> JSONResponse:
    return JSONResponse(status_code=202, content={"op_id": op.id, "status": op.status})


@router.post("/videos/generate")
async def generate_video(
    body: VideoGenerateRequest,
    background: bool = False,
    session: Session = Depends(get_session),
):
    kwargs = body.model_dump()
    if background:
        op = op_service.start_op(
            "video_generation",
            lambda s: video_generation_service.generate_video(
                s,
                **kwargs,
                on_stage=lambda stage: _record_stage(op_id, stage),
            ),
            project_id=project_service.active_project_id(session),
            summarize=lambda result: result,
        )
        op_id = op.id
        return _op_response(op)
    return await video_generation_service.generate_video(session, **kwargs)


def _record_stage(op_id: str, stage: str) -> None:
    from app import database
    from sqlmodel import Session as DbSession

    with DbSession(database.engine) as session:
        op_service.update_op_progress(session, op_id, stage)
