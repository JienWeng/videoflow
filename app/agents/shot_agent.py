"""Shot agent — break a SceneSpec into an ordered ShotList."""

from __future__ import annotations

from app.agents.base import as_block, run_agent
from app.schemas import SceneSpec, ShotList


async def generate_shots(*, scene: SceneSpec, client=None) -> ShotList:
    prompt = "\n\n".join(
        [
            as_block("Scene", scene),
            "Produce a ShotList for this scene. Set scene_id to the scene's id. "
            "Shot durations should sum to roughly the scene duration.",
        ]
    )
    return await run_agent(
        agent="shot_agent",
        response_model=ShotList,
        user_prompt=prompt,
        client=client,
    )
