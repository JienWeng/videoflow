"""Cheap pre-render self-critique of a RenderSpec (text-only, before paying for
Kling). The critic may rewrite the prompt / per-shot prompts, but never the
reference structure (that stays under enforce_render_defaults)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.render_schema import StoryboardShot


class SpecCritique(BaseModel):
    ok: bool = Field(description="True if the spec is renderable as-is")
    issues: list[str] = Field(default_factory=list)
    revised_prompt: str | None = None
    revised_multi_prompt: list[StoryboardShot] | None = None
