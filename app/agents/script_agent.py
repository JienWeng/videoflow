"""Script agent — story idea -> ScriptDraft."""

from __future__ import annotations

from app.agents.base import as_block, run_agent
from app.schemas import ScriptDraft


async def generate_script(
    *,
    idea: str,
    target_duration: int | None = None,
    scene_count: int | None = None,
    style: dict | None = None,
    characters: list[dict] | None = None,
    generation_brief: dict | None = None,
    client=None,
) -> ScriptDraft:
    parts = [
        as_block("Story idea", idea),
        as_block("Target total duration (s)", target_duration or "unspecified"),
    ]
    if style:
        parts.append(as_block("Project style guide", style))
    if generation_brief:
        parts.append(as_block("Generation brief (follow throughout planning and rendering)", generation_brief))
    if characters:
        # Contract: the agent writes EXACT catalog names; downstream
        # auto_link_scene converts those bare names to @tags and DB links.
        parts.append(
            as_block("Existing characters (cast them by their EXACT names)", characters)
        )
    if scene_count is not None:
        parts.append(f"Produce EXACTLY {scene_count} scene(s).")
    parts.append("Produce a ScriptDraft with an ordered list of scenes.")
    prompt = "\n\n".join(parts)
    return await run_agent(
        agent="script_agent",
        response_model=ScriptDraft,
        user_prompt=prompt,
        client=client,
    )
