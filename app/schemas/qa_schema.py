"""QA agent output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# The dimensions the vision QA judges. Each is scored 1-5 with frame-cited
# evidence so the supervision policy can target the WORST one (e.g. fix only the
# shot with a continuity break) instead of regenerating the whole video.
DimensionName = Literal[
    "character_consistency",
    "continuity",
    "scene_match",
    "camera_match",
    "audio_voice",
    "artifacts_text",
]


class DimensionScore(BaseModel):
    name: DimensionName
    score: int = Field(ge=1, le=5, description="1 (broken) .. 5 (perfect)")
    evidence: list[str] = Field(
        default_factory=list,
        description="Frame-cited observations, e.g. 'frame 3: Grace outfit changed'",
    )


class QAResult(BaseModel):
    """Judgement of a rendered output against its scene/shot requirements.

    `score`/`passed`/`issues`/`recommendation` are the original (backward-compatible)
    surface used by qa_service storage and retry_output. `dimensions`/`worst_dimension`
    are OPTIONAL detail added for the supervision loop — old persisted `qa_json` rows
    (without them) still validate.
    """

    score: int = Field(ge=1, le=10, description="Overall quality score, 1-10")
    passed: bool
    issues: list[str] = Field(
        default_factory=list, description="Specific problems found"
    )
    recommendation: Literal["accept", "reject", "regenerate"]
    dimensions: list[DimensionScore] = Field(default_factory=list)
    worst_dimension: DimensionName | None = None

    def dimension(self, name: DimensionName) -> int | None:
        """The score for one dimension, or None if it wasn't reported."""
        for d in self.dimensions:
            if d.name == name:
                return d.score
        return None
