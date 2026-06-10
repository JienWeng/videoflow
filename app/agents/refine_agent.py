"""Refine agent — rewrite a scene's or shot's editable fields from a user instruction."""

from __future__ import annotations

from app.agents.base import as_block, run_agent
from app.schemas import SceneRefinement, ShotRefinement


async def refine_scene(*, scene: dict, instruction: str, client=None) -> SceneRefinement:
    prompt = "\n\n".join(
        [
            as_block("Current scene", scene),
            as_block("User instruction", instruction),
            "Return ONLY the scene fields that should change; leave the rest null.",
        ]
    )
    return await run_agent(
        agent="refine_agent",
        response_model=SceneRefinement,
        user_prompt=prompt,
        client=client,
    )


async def refine_shot(
    *, shot: dict, scene_summary: str, instruction: str, client=None
) -> ShotRefinement:
    prompt = "\n\n".join(
        [
            as_block("Current shot", shot),
            as_block("Scene context", scene_summary),
            as_block("User instruction", instruction),
            "Return ONLY the shot fields that should change; leave the rest null.",
        ]
    )
    return await run_agent(
        agent="refine_agent",
        response_model=ShotRefinement,
        user_prompt=prompt,
        client=client,
    )
