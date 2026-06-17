"""Targeted render correction — a structured patch from a vision reviser that SAW
the bad frames, instead of a blind prompt suffix. Applied field-by-field, then the
render invariants are re-asserted (voice/sound/negatives + the <=7 reference cap)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.render_schema import AspectRatio


class ShotPromptPatch(BaseModel):
    index: int = Field(ge=1, description="1-based multi_prompt index to replace")
    prompt: str


class ReferencePatch(BaseModel):
    # 'strengthen' is advisory (the reviser emphasises @name in a shot prompt
    # instead); only swap/remove change the reference structure. A reviser must
    # NEVER introduce a new character name (clone risk) — name must already exist.
    op: Literal["strengthen", "swap", "remove"]
    name: str
    asset_id: str | None = None  # for 'swap'


class RenderSpecPatch(BaseModel):
    rationale: str
    main_prompt: str | None = None
    shot_prompts: list[ShotPromptPatch] = Field(default_factory=list)
    references: list[ReferencePatch] = Field(default_factory=list)
    aspect_ratio: AspectRatio | None = None
