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
    assets: list[dict] | None = None,
    available_characters: list[dict] | None = None,
    library: list[dict] | None = None,
    style: dict | None = None,
    story: dict | None = None,
    client=None,
) -> SceneSpec:
    parts = [
        as_block("Scene id", scene_id),
        as_block("Title", title),
        as_block("Summary", summary),
        as_block("Suggested duration (s)", suggested_duration),
        as_block("Character bibles", [b.model_dump() for b in character_bibles or []]),
        as_block("Available asset ids", available_asset_ids or []),
    ]
    if assets:
        parts.append(as_block("Linked assets (use @Name)", assets))
    # Database catalogs (bibles above stay the authoritative cast context).
    # Contract: the agent writes EXACT catalog names; auto_link_scene then
    # converts those mentions to @tags and DB links automatically.
    if available_characters:
        parts.append(
            as_block(
                "Other available characters (cast by EXACT name if the scene needs them)",
                available_characters,
            )
        )
    if library:
        parts.append(
            as_block("Asset library (reference by EXACT name with @ to reuse)", library)
        )
    if style:
        parts.append(as_block("Project style guide", style))
    if story:
        parts.append(as_block("Overall story and sibling scenes (keep continuity)", story))
    parts.append(
        "Produce a SceneSpec. Set scene_id to the given id. Honour every "
        "visual_rule in the character bibles."
        + (" Match the project style guide in every visual choice." if style else "")
    )
    prompt = "\n\n".join(parts)
    return await run_agent(
        agent="scene_agent",
        response_model=SceneSpec,
        user_prompt=prompt,
        client=client,
    )
