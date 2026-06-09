"""QA agent output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class QAResult(BaseModel):
    """Judgement of a rendered output against its scene/shot requirements."""

    score: int = Field(ge=1, le=10, description="Overall quality score, 1-10")
    passed: bool
    issues: list[str] = Field(
        default_factory=list, description="Specific problems found"
    )
    recommendation: Literal["accept", "reject", "regenerate"]
