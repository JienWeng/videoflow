"""Style agent — derive ONE reusable project style guide from the story."""

from __future__ import annotations

from app.agents.base import as_block, run_agent
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
        as_block("Scripts (overall story)", scripts or []),
        as_block("Scenes", scenes or []),
        as_block("Characters", characters or []),
        as_block("Assets", assets or []),
    ]
    return await run_agent(
        agent="style_agent",
        response_model=StyleSpec,
        user_prompt="\n\n".join(parts),
        client=client,
    )
