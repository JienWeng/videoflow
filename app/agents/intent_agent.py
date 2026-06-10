"""Intent agent: classify a chat message against the project's entity catalogs."""

from __future__ import annotations

from app.agents.base import as_block, run_agent
from app.llm.structured_client import StructuredLLMClient
from app.schemas import Intent


async def classify_intent(
    *,
    message: str,
    scenes: list[dict],
    characters: list[dict],
    outputs: list[dict] | None = None,
    client: StructuredLLMClient | None = None,
) -> Intent:
    parts = [
        as_block("User message", message),
        as_block("Scenes catalog", scenes),
        as_block("Characters catalog", characters),
    ]
    if outputs:
        parts.append(as_block("Render outputs catalog", outputs))
    return await run_agent(
        agent="intent_agent",
        response_model=Intent,
        user_prompt="\n\n".join(parts),
        client=client,
    )
