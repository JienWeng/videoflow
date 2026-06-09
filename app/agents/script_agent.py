"""Script agent — story idea -> ScriptDraft."""

from __future__ import annotations

from app.agents.base import as_block, run_agent
from app.schemas import ScriptDraft


async def generate_script(
    *,
    idea: str,
    target_duration: int | None = None,
    client=None,
) -> ScriptDraft:
    prompt = "\n\n".join(
        [
            as_block("Story idea", idea),
            as_block("Target total duration (s)", target_duration or "unspecified"),
            "Produce a ScriptDraft with an ordered list of scenes.",
        ]
    )
    return await run_agent(
        agent="script_agent",
        response_model=ScriptDraft,
        user_prompt=prompt,
        client=client,
    )
