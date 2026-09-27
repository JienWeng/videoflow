"""Character bible — persistent character identity."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CharacterBible(BaseModel):
    """The canonical identity that keeps a character consistent across renders."""

    character_id: str
    name: str
    appearance: str = Field(
        description="Detailed physical appearance: face, hair, build, default outfit"
    )
    personality: str = Field(description="Personality and demeanour")
    visual_rules: list[str] = Field(
        default_factory=list,
        description="Hard continuity rules, e.g. 'always wears red scarf'",
    )
    voice_rules: list[str] = Field(
        default_factory=list,
        description="Voice/speech traits, e.g. 'low calm voice, British accent'",
    )
    sample_dialogue: str = Field(
        default="",
        description="One short natural spoken line that demonstrates the character's voice",
    )
    reference_asset_ids: list[str] = Field(
        default_factory=list, description="IDs of reference images for this character"
    )
