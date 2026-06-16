"""Intent agent: classify a chat message against the project's entity catalogs."""

from __future__ import annotations

from app.agents.base import as_block, gated_block, run_agent
from app.llm.structured_client import StructuredLLMClient
from app.schemas import Intent


async def classify_intent(
    *,
    message: str,
    scenes: list[dict],
    characters: list[dict],
    outputs: list[dict] | None = None,
    history: list[dict] | None = None,
    state: dict | None = None,
    client: StructuredLLMClient | None = None,
) -> Intent:
    parts = []
    parts += gated_block("intent_agent", "history", "Conversation so far", history)
    parts += [
        as_block("User message", message),
        as_block("Scenes catalog", scenes),
        as_block("Characters catalog", characters),
    ]
    parts += gated_block("intent_agent", "outputs", "Render outputs catalog", outputs)
    parts += gated_block(
        "intent_agent",
        "state",
        "Project state (counts and pipeline progress)",
        state,
    )
    return await run_agent(
        agent="intent_agent",
        response_model=Intent,
        user_prompt="\n\n".join(parts),
        client=client,
    )
