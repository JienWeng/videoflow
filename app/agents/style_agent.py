"""Style agent — derive ONE reusable project style guide from the story."""

from __future__ import annotations

from app.agents.base import gated_block, run_agent
from app.llm.structured_client import StructuredLLMClient
from app.schemas import StyleSpec


async def derive_style(
    *,
    scenes: list[dict] | None = None,
    characters: list[dict] | None = None,
    assets: list[dict] | None = None,
    scripts: list[dict] | None = None,
    client: StructuredLLMClient | None = None,
) -> StyleSpec:
    parts = [
        *gated_block("style_agent", "scripts", "Scripts (overall story)", scripts),
        *gated_block("style_agent", "scenes", "Scenes", scenes),
        *gated_block("style_agent", "characters", "Characters", characters),
        *gated_block("style_agent", "assets", "Assets", assets),
    ]
    return await run_agent(
        agent="style_agent",
        response_model=StyleSpec,
        user_prompt="\n\n".join(parts),
        client=client,
    )
