"""Director agent — chooses the single best next action for an autonomous run.

It sees the run state (what artifacts exist, the latest per-dimension QA verdict,
attempts used, remaining budget) and returns one `DirectorDecision`. The loop
enforces the hard guardrails (budget / attempt caps) around this — the director
proposes, the governor disposes.
"""

from __future__ import annotations

from app.agents.base import as_block, run_agent
from app.schemas.director_schema import DirectorDecision


async def decide_next(*, state: dict, client=None) -> DirectorDecision:
    prompt = "\n\n".join(
        [
            as_block("Current run state", state),
            "Choose the SINGLE best next action and explain why in one sentence. "
            "Render only when shots exist; caption only after an acceptable render; "
            "finish when the video is captioned or when budget/attempts are low.",
        ]
    )
    return await run_agent(
        agent="director",
        response_model=DirectorDecision,
        user_prompt=prompt,
        client=client,
    )
