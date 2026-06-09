"""Script / scene / shot wire schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.config import get_settings
from app.schemas.common import AspectRatio


class ShotSpec(BaseModel):
    """A single shot within a scene."""

    shot_id: str
    duration: int = Field(ge=1, le=15, description="Shot duration in seconds")
    prompt: str = Field(description="What happens in this shot")
    camera: str | None = Field(default=None, description="Camera framing, e.g. 'close-up'")
    movement: str | None = Field(default=None, description="Camera movement, e.g. 'slow push-in'")
    asset_ids: list[str] = Field(default_factory=list)


class SceneSpec(BaseModel):
    """A scene: a coherent unit broken into shots."""

    scene_id: str
    title: str
    summary: str
    duration: int = Field(ge=3, le=60, description="Total scene duration in seconds")
    aspect_ratio: AspectRatio = Field(
        default_factory=lambda: get_settings().default_aspect_ratio
    )
    character_ids: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    shots: list[ShotSpec] = Field(default_factory=list)


class ScriptScene(BaseModel):
    """A scene stub produced by the script agent (pre-shot-breakdown)."""

    scene_id: str
    title: str
    summary: str
    suggested_duration: int = Field(ge=3, le=60)


class ScriptDraft(BaseModel):
    """Top-level output of the script agent. (instructor needs a root model.)"""

    title: str
    summary: str
    scenes: list[ScriptScene] = Field(default_factory=list)
