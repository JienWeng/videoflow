"""Asset-planner agent — define the visual assets (props/backgrounds/tools) a
scene still needs, each with a standalone text-to-image prompt."""

from __future__ import annotations

from app.agents.base import as_block, gated_block, run_agent
from app.llm.structured_client import StructuredLLMClient
from app.schemas import AssetPlan


async def plan_assets(
    *,
    scene_summary: str,
    scene_json: dict | None = None,
    existing_assets: list[dict] | None = None,
    library: list[dict] | None = None,
    instruction: str = "",
    shots: list[dict] | None = None,
    style: dict | None = None,
    characters: list[dict] | None = None,
    story: dict | None = None,
    client: StructuredLLMClient | None = None,
) -> AssetPlan:
    parts = [
        as_block("Scene summary", scene_summary),
        as_block("Scene spec", scene_json or {}),
        as_block("Existing assets (do NOT duplicate)", existing_assets or []),
    ]
    parts += gated_block(
        "asset_planner",
        "library",
        "Asset library (REUSE these by exact name instead of proposing "
        "similar new ones)",
        library,
    )
    parts += gated_block(
        "asset_planner", "characters", "Cast (props must fit these characters)", characters
    )
    parts += gated_block(
        "asset_planner",
        "story",
        "Overall story and sibling scenes (keep continuity)",
        story,
    )
    parts += gated_block("asset_planner", "style", "Style guide", style)
    parts += gated_block("asset_planner", "shots", "Scene shots", shots)
    if instruction:
        parts.append(as_block("User instruction", instruction))
    return await run_agent(
        agent="asset_planner",
        response_model=AssetPlan,
        user_prompt="\n\n".join(parts),
        client=client,
    )
