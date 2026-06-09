"""Asset recognition output."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import AssetType


class AssetMetadata(BaseModel):
    """Structured description of an uploaded (or generated) asset."""

    asset_id: str = Field(description="ID of the asset this metadata describes")
    asset_type: AssetType
    name: str = Field(description="Short human-readable name")
    tags: list[str] = Field(default_factory=list, description="Searchable tags")
    description: str = Field(description="One- or two-sentence description")
    character_id: str | None = Field(
        default=None, description="Linked character, if this asset depicts one"
    )
