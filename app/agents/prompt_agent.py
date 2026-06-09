"""Prompt agent — assemble a provider-ready RenderSpec for one shot.

Produces a RenderSpec whose prompt weaves @Name tokens for each supplied named
reference image (e.g. "@Kling Lipstick streaks across @Image"), and whose
reference_images mirror those name/asset_id pairs so the render pipeline can
resolve them into the Kling images[] array. Voice/sound default on.
"""

from __future__ import annotations

from app.agents.base import as_block, run_agent
from app.config import get_settings
from app.schemas import CharacterBible, RenderSpec, ShotSpec


async def build_render_spec(
    *,
    scene_id: str,
    scene_summary: str,
    shot: ShotSpec,
    aspect_ratio: str | None = None,
    named_references: list[dict] | None = None,
    character_bibles: list[CharacterBible] | None = None,
    video_asset_id: str | None = None,
    dialogue_language: str = "English",
    client=None,
) -> RenderSpec:
    """`named_references` is a list of {"name": str, "asset_id": str} the model
    should reference by @name and echo into reference_images verbatim.
    `dialogue_language` controls the language of the spoken 「 」 lines."""
    named_references = named_references or []
    aspect_ratio = aspect_ratio or get_settings().default_aspect_ratio
    prompt = "\n\n".join(
        [
            as_block("Scene id", scene_id),
            as_block("Scene summary", scene_summary),
            as_block("Shot", shot),
            as_block("Aspect ratio", aspect_ratio),
            as_block("DIALOGUE LANGUAGE (write all spoken 「」 lines in this language)", dialogue_language),
            as_block("Named reference images (use @name, echo into reference_images)", named_references),
            as_block("Character bibles", [b.model_dump() for b in character_bibles or []]),
            as_block("Reference video asset id", video_asset_id or "none"),
            "Produce a RenderSpec as a SHOT SCRIPT. Set scene_id and shot_id "
            "(shot.shot_id). Set duration to the shot duration (3-15). Each shot "
            "must follow '<framing>, background <ref>. <action with @names>. @Name "
            "says, 「<line>」.' with dialogue in the DIALOGUE LANGUAGE. Reference "
            "each named image with @name inline and echo the name/asset_id pairs "
            "into reference_images. Keep sound and keep_original_sound true.",
        ]
    )
    spec = await run_agent(
        agent="prompt_agent",
        response_model=RenderSpec,
        user_prompt=prompt,
        client=client,
    )
    # Defensive: force fields the caller controls, in case the model drifts.
    spec.scene_id = scene_id
    spec.shot_id = shot.shot_id
    spec.aspect_ratio = aspect_ratio
    if video_asset_id and not spec.video_asset_id:
        spec.video_asset_id = video_asset_id
    return spec
