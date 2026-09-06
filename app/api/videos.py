"""Simple user-facing video generation endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.database import get_session
from app.services import op_service, video_generation_service

router = APIRouter(tags=["videos"])


class VideoGenerateRequest(BaseModel):
    idea: str = Field(min_length=1, max_length=8000)
    target_duration: int | None = Field(default=None, ge=3, le=300)
    scene_count: int | None = Field(default=None, ge=1, le=20)
    style: str = "2d-picture-book"
    aspect_ratio: str = "9:16"
    language: str = "English"
    conversation_mode: str = "dialogue"
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
            lambda s: video_generation_service.generate_video(s, **kwargs),
            summarize=lambda result: result,
        )
        return _op_response(op)
    return await video_generation_service.generate_video(session, **kwargs)
