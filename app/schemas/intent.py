"""Guided-intent chat: the LLM classifies a message; it never executes anything."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class IntentAction(str, Enum):
    generate_script = "generate_script"
    generate_scenes = "generate_scenes"
    generate_shots = "generate_shots"
    storyboard = "storyboard"
    render_scene = "render_scene"
    render_shot = "render_shot"
    caption = "caption"
    retry_render = "retry_render"
    generate_assets = "generate_assets"
    refine_scene = "refine_scene"
    refine_shot = "refine_shot"
    delete_scene = "delete_scene"
    style_ingest = "style_ingest"
    plan_assets = "plan_assets"
    unknown = "unknown"


class Intent(BaseModel):
    action: IntentAction = IntentAction.unknown
    scene_id: str | None = None
    character_id: str | None = None
    shot_id: str | None = None
    output_id: str | None = None
    style: str | None = None       # caption style
    language: str | None = None    # caption language
    idea: str | None = None        # generate_script: the story idea text
    scene_count: int | None = Field(default=None, ge=1, le=20)  # how many scenes/videos requested
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reply: str = ""                # one-line natural-language reply to show in chat
