"""RenderSpec — the contract between the prompt agent and the video provider."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.config import get_settings
from app.schemas.common import AspectRatio


class ReferenceImage(BaseModel):
    """A named reference image. `name` is the token used in the prompt (@name);
    `asset_id` points at a stored asset that is uploaded and placed in images[]."""

    name: str = Field(description="Reference token used in the prompt, e.g. 'Kling Lipstick'")
    asset_id: str = Field(description="Stored asset id to resolve to a public URL")


class StoryboardShot(BaseModel):
    """One shot of a multi-shot storyboard."""

    prompt: str = Field(description="Prompt for this shot")
    duration: int = Field(ge=1, le=15, description="Shot duration in seconds (>= 1)")


class RenderSpec(BaseModel):
    """Provider-agnostic render request mapped to the configured video model."""

    provider: Literal["atlascloud", "openrouter"] = "atlascloud"
    model: str = "minimax/h3-developer/text-to-video"

    scene_id: str
    shot_id: str | None = None

    aspect_ratio: AspectRatio = Field(
        default_factory=lambda: get_settings().default_aspect_ratio
    )
    duration: int = Field(default=5, ge=3, le=15, description="Total duration, 3-15s")
    prompt: str = Field(description="Positive prompt; may use @Name reference tokens")

    # Reference inputs ---------------------------------------------------------
    reference_images: list[ReferenceImage] = Field(
        default_factory=list,
        description="Named reference images woven into the prompt and images[]",
    )
    extra_image_asset_ids: list[str] = Field(
        default_factory=list,
        description="Additional (unnamed) reference image asset ids",
    )
    first_frame_asset_id: str | None = Field(
        default=None, description="Optional exact first-frame image for image-to-video"
    )
    last_frame_asset_id: str | None = Field(
        default=None, description="Optional exact last-frame image for image-to-video"
    )
    video_asset_id: str | None = Field(
        default=None, description="Optional single reference video asset id"
    )

    # Audio / voice ------------------------------------------------------------
    sound: bool = Field(default=True, description="Generate audio/voice for the video")
    keep_original_sound: bool = Field(
        default=True, description="Keep the reference video's original sound"
    )

    # Multi-shot ---------------------------------------------------------------
    multi_shot: bool = False
    shot_type: Literal["customize", "intelligence"] | None = None
    multi_prompt: list[StoryboardShot] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_multishot(self) -> RenderSpec:
        if self.multi_shot:
            if self.shot_type is None:
                raise ValueError("shot_type is required when multi_shot=true")
            if self.shot_type == "customize":
                if not self.multi_prompt:
                    raise ValueError(
                        "multi_prompt is required when shot_type='customize'"
                    )
                total = sum(s.duration for s in self.multi_prompt)
                if total != self.duration:
                    raise ValueError(
                        f"sum of shot durations ({total}) must equal "
                        f"top-level duration ({self.duration})"
                    )
        else:
            # Ignore storyboard fields when multi_shot is off, but flag misuse.
            if self.shot_type is not None or self.multi_prompt:
                raise ValueError(
                    "shot_type/multi_prompt only valid when multi_shot=true"
                )
        return self

    @property
    def all_reference_image_asset_ids(self) -> list[str]:
        """Ordered, de-duplicated asset ids for the provider images[] array:
        named references first (prompt @-token order), then extras."""
        seen: set[str] = set()
        ordered: list[str] = []
        for ref in self.reference_images:
            if ref.asset_id not in seen:
                seen.add(ref.asset_id)
                ordered.append(ref.asset_id)
        for aid in self.extra_image_asset_ids:
            if aid not in seen:
                seen.add(aid)
                ordered.append(aid)
        return ordered
