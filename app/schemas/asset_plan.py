"""Asset-planning schemas — what visual assets a scene still needs.

The planner outputs PlannedAssets whose `image_prompt` is a complete standalone
text-to-image prompt (consistent with the scene's style/lighting) that the ERNIE
provider can render directly into a registered Asset.
"""

from __future__ import annotations

from pydantic import BaseModel


class PlannedAsset(BaseModel):
    name: str
    asset_type: str = "prop"  # prop | background | tool | other
    description: str = ""
    image_prompt: str  # full text-to-image prompt, consistent with scene style/lighting


class AssetPlan(BaseModel):
    assets: list[PlannedAsset] = []
    reasoning: str = ""
