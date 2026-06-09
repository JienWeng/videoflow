"""Scene agent — expand a scene stub into a full SceneSpec."""

from __future__ import annotations

from app.agents.base import as_block, run_agent
from app.schemas import CharacterBible, SceneSpec


async def generate_scene(
    *,
    scene_id: str,
    title: str,
    summary: str,
    suggested_duration: int,
    character_bibles: list[CharacterBible] | None = None,
    available_asset_ids: list[str] | None = None,
    client=None,
) -> SceneSpec:
    prompt = "\n\n".join(
        [
            as_block("Scene id", scene_id),
            as_block("Title", title),
            as_block("Summary", summary),
            as_block("Suggested duration (s)", suggested_duration),
            as_block("Character bibles", [b.model_dump() for b in character_bibles or []]),
            as_block("Available asset ids", available_asset_ids or []),
            "Produce a SceneSpec. Set scene_id to the given id. Honour every "
            "visual_rule in the character bibles.",
        ]
    )
    return await run_agent(
        agent="scene_agent",
        response_model=SceneSpec,
        user_prompt=prompt,
        client=client,
    )
