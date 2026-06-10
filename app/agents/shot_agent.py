"""Shot agent — break a SceneSpec into an ordered ShotList."""

from __future__ import annotations

from app.agents.base import as_block, run_agent
from app.schemas import CharacterBible, SceneSpec, ShotList


async def generate_shots(
    *,
    scene: SceneSpec,
    style: dict | None = None,
    characters: list[CharacterBible] | None = None,
    assets: list[dict] | None = None,
    client=None,
) -> ShotList:
    parts = [as_block("Scene", scene)]
    if characters:
        parts.append(
            as_block(
                "Cast (use @Name to reference them)",
                [b.model_dump() for b in characters],
            )
        )
    if assets:
        parts.append(as_block("Linked assets (use @Name)", assets))
    if style:
        parts.append(as_block("Project style guide", style))
    parts.append(
        "Produce a ShotList for this scene. Set scene_id to the scene's id. "
        "Shot durations should sum to roughly the scene duration."
        + (" Match the project style guide in every visual choice." if style else "")
    )
    prompt = "\n\n".join(parts)
    return await run_agent(
        agent="shot_agent",
        response_model=ShotList,
        user_prompt=prompt,
        client=client,
    )
