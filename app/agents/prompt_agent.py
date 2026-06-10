"""Prompt agent — assemble a provider-ready RenderSpec for one shot.

Produces a RenderSpec whose prompt weaves @Name tokens for each supplied named
reference image (e.g. "@Kling Lipstick streaks across @Image"), and whose
reference_images mirror those name/asset_id pairs so the render pipeline can
resolve them into the Kling images[] array. Voice/sound default on.
"""

from __future__ import annotations

from app.agents.base import as_block, run_agent
from app.config import get_settings
from app.schemas import CharacterBible, ReferenceImage, RenderSpec, ShotSpec

# Captions/subtitles are added in post-production by the caption pipeline —
# the video model must never draw text. Shared by enforce_render_defaults and
# render_service so the wording can't drift between the two render paths.
NO_TEXT_NEGATIVE = "no subtitles, no on-screen text, no captions"


def collect_named_references(
    *,
    named_references: list[dict],
    character_bibles: list[CharacterBible],
    shot_asset_ids: list[str],
    asset_names: dict[str, str],
) -> list[dict]:
    """Merge every available reference image into one named list for Kling:
    caller-supplied refs first (verbatim), then character bible reference images
    (named after the character, "@Name 2" for extras), then shot/scene assets
    (named after the asset). Asset ids are de-duplicated (first name wins) and
    @names are kept unique so prompt tokens resolve unambiguously."""
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    refs: list[dict] = []

    def add(name: str, asset_id: str) -> None:
        if asset_id in seen_ids:
            return
        unique = name
        n = 2
        while unique in seen_names:
            unique = f"{name} {n}"
            n += 1
        seen_ids.add(asset_id)
        seen_names.add(unique)
        refs.append({"name": unique, "asset_id": asset_id})

    for ref in named_references:
        add(ref["name"], ref["asset_id"])
    for bible in character_bibles:
        for aid in bible.reference_asset_ids:
            add(bible.name, aid)
    for aid in shot_asset_ids:
        add(asset_names.get(aid) or aid, aid)
    return refs


def enforce_render_defaults(spec: RenderSpec, *, named_references: list[dict]) -> None:
    """Post-LLM enforcement of fields the pipeline guarantees: voice/sound on,
    every supplied reference present in reference_images, and multi-shot always
    enabled (Kling 'intelligence' mode when the model wrote no storyboard)."""
    spec.sound = True
    spec.keep_original_sound = True
    if not spec.multi_shot:
        spec.multi_shot = True
        spec.shot_type = "intelligence"
        spec.multi_prompt = []
    if "no subtitles" not in spec.prompt.lower():
        spec.prompt = f"{spec.prompt} — {NO_TEXT_NEGATIVE} (added in post)."
    present = {r.asset_id for r in spec.reference_images}
    for ref in named_references:
        if ref["asset_id"] not in present:
            present.add(ref["asset_id"])
            spec.reference_images.append(
                ReferenceImage(name=ref["name"], asset_id=ref["asset_id"])
            )


async def build_render_spec(
    *,
    scene_id: str,
    scene_summary: str,
    shot: ShotSpec,
    aspect_ratio: str | None = None,
    named_references: list[dict] | None = None,
    character_bibles: list[CharacterBible] | None = None,
    asset_names: dict[str, str] | None = None,
    video_asset_id: str | None = None,
    dialogue_language: str = "English",
    style: dict | None = None,
    client=None,
) -> RenderSpec:
    """`named_references` is a list of {"name": str, "asset_id": str} the model
    should reference by @name and echo into reference_images verbatim. Character
    bible reference images and the shot's asset_ids (display names supplied via
    `asset_names`) are merged in so every available image reaches Kling images[].
    `dialogue_language` controls the language of the spoken 「 」 lines."""
    character_bibles = character_bibles or []
    named_references = collect_named_references(
        named_references=named_references or [],
        character_bibles=character_bibles,
        shot_asset_ids=list(shot.asset_ids or []),
        asset_names=asset_names or {},
    )
    aspect_ratio = aspect_ratio or get_settings().default_aspect_ratio
    style_blocks = [as_block("Project style guide", style)] if style else []
    prompt = "\n\n".join(
        [
            as_block("Scene id", scene_id),
            as_block("Scene summary", scene_summary),
            as_block("Shot", shot),
            as_block("Aspect ratio", aspect_ratio),
            *style_blocks,
            as_block("DIALOGUE LANGUAGE (write all spoken 「」 lines in this language)", dialogue_language),
            as_block("Named reference images (use @name, echo into reference_images)", named_references),
            as_block("Character bibles", [b.model_dump() for b in character_bibles]),
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
    enforce_render_defaults(spec, named_references=named_references)
    return spec
