"""The autonomous director's decision — one action per turn."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DirectorAction = Literal[
    "generate_script",
    "expand_scene",
    "generate_shots",
    "generate_storyboard",
    "render_scene",
    "revise_render",
    "regenerate_render",
    "caption",
    "finish",
    "abort",
]


class DirectorDecision(BaseModel):
    rationale: str = Field(description="One sentence: why this action now.")
    action: DirectorAction
    notes: str | None = None
