"""Asset-planner agent — define the visual assets (props/backgrounds/tools) a
scene still needs, each with a standalone text-to-image prompt."""

from __future__ import annotations

from app.agents.base import as_block, run_agent
from app.llm.structured_client import StructuredLLMClient
from app.schemas import AssetPlan


async def plan_assets(
    *,
    scene_summary: str,
    scene_json: dict | None = None,
    existing_assets: list[dict] | None = None,
    instruction: str = "",
    client: StructuredLLMClient | None = None,
) -> AssetPlan:
    parts = [
        as_block("Scene summary", scene_summary),
        as_block("Scene spec", scene_json or {}),
        as_block("Existing assets (do NOT duplicate)", existing_assets or []),
    ]
    if instruction:
        parts.append(as_block("User instruction", instruction))
    return await run_agent(
        agent="asset_planner",
        response_model=AssetPlan,
        user_prompt="\n\n".join(parts),
        client=client,
    )
