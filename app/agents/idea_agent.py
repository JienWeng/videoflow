"""Idea agent — raw user idea -> two developed concept options + recommendation."""

from __future__ import annotations

from app.agents.base import as_block, gated_block, run_agent
from app.schemas import IdeaOptions


async def develop_idea(
    *,
    idea: str,
    characters: list[dict] | None = None,
    style: dict | None = None,
    client=None,
) -> IdeaOptions:
    parts = [as_block("Raw idea", idea)]
    parts += gated_block("idea_agent", "style", "Project style guide", style)
    # Contract: the agent writes EXACT catalog names so downstream script and
    # scene agents (and auto_link_scene) keep casting them by name.
    parts += gated_block(
        "idea_agent",
        "characters",
        "Existing characters (cast them by their EXACT names)",
        characters,
    )
    parts.append("Develop EXACTLY TWO concept options and recommend one.")
    prompt = "\n\n".join(parts)
    return await run_agent(
        agent="idea_agent",
        response_model=IdeaOptions,
        user_prompt=prompt,
        client=client,
    )
