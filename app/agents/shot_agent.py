"""Shot agent — break a SceneSpec into an ordered ShotList."""

from __future__ import annotations

from app.agents.base import as_block, gated_block, run_agent
from app.llm import skills
from app.schemas import CharacterBible, SceneSpec, ShotList


async def generate_shots(
    *,
    scene: SceneSpec,
    style: dict | None = None,
    story: dict | None = None,
    characters: list[CharacterBible] | None = None,
    assets: list[dict] | None = None,
    client=None,
) -> ShotList:
    parts = [as_block("Scene", scene)]
    parts += gated_block(
        "shot_agent",
        "characters",
        "Cast (use @Name to reference them)",
        [b.model_dump() for b in characters] if characters else None,
    )
    parts += gated_block("shot_agent", "assets", "Linked assets (use @Name)", assets)
    parts += gated_block("shot_agent", "style", "Project style guide", style)
    parts += gated_block(
        "shot_agent",
        "story",
        "Overall story and sibling scenes (keep continuity)",
        story,
    )
    style_on = bool(style) and "style" not in skills.context_excludes("shot_agent")
    parts.append(
        "Produce a ShotList for this scene. Set scene_id to the scene's id. "
        "Shot durations should sum to roughly the scene duration."
        + (" Match the project style guide in every visual choice." if style_on else "")
    )
    prompt = "\n\n".join(parts)
    return await run_agent(
        agent="shot_agent",
        response_model=ShotList,
        user_prompt=prompt,
        client=client,
    )
