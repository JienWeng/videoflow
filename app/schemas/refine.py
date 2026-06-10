"""AI-refinement schemas — partial-update deltas produced by the refine agent."""

from __future__ import annotations

from pydantic import BaseModel


class SceneRefinement(BaseModel):
    """Only fields the agent wants to change; None = keep."""

    title: str | None = None
    summary: str | None = None
    duration: int | None = None
    aspect_ratio: str | None = None
    note: str = ""  # one-line explanation of what changed and why


class ShotRefinement(BaseModel):
    """Only fields the agent wants to change; None = keep."""

    prompt: str | None = None
    duration: int | None = None
    camera: str | None = None
    movement: str | None = None
    note: str = ""
