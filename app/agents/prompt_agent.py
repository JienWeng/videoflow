"""Prompt agent — assemble a provider-ready RenderSpec for one shot.

Produces a RenderSpec whose prompt weaves @Name tokens for each supplied named
reference image (e.g. "@Kling Lipstick streaks across @Image"), and whose
reference_images mirror those name/asset_id pairs so the render pipeline can
resolve them into the Kling images[] array. Voice/sound default on.
"""

from __future__ import annotations

import logging

from app.agents.base import as_block, run_agent
from app.config import get_settings
from app.schemas import CharacterBible, ReferenceImage, RenderSpec, ShotSpec

logger = logging.getLogger(__name__)

# Captions/subtitles are added in post-production by the caption pipeline —
# the video model must never draw text. Shared by enforce_render_defaults and
# render_service so the wording can't drift between the two render paths.
NO_TEXT_NEGATIVE = "no subtitles, no on-screen text, no captions"

# Kling renders a clone whenever it suspects two named images are two people —
# enforced in every render path (prompt agent + whole-scene) alongside the
# one-image-per-character rule in collect_named_references.
NO_CLONE_NEGATIVE = (
    "exactly one instance of each character, no duplicated characters, "
    "no clones or twins"
)


def collect_named_references(
    *,
    named_references: list[dict],
    character_bibles: list[CharacterBible],
    shot_asset_ids: list[str],
    asset_names: dict[str, str],
) -> list[dict]:
    """Merge every available reference image into one named list for Kling:
    caller-supplied refs first (verbatim), then ONE reference image per
    character bible (named after the character), then shot/scene assets (named
    after the asset). Asset ids are de-duplicated (first name wins).

    Each character maps to exactly ONE named image: Kling treats two named
    images of the same person ("@乐乐" and "@乐乐 2") as two distinct people
    and renders clones. So extra character sheets are never sent, and any
    later entry whose name collides with an already-added character (e.g. a
    shot asset that is another photo of them) is SKIPPED entirely. Only
    non-character names (two different props sharing a name) keep the " 2"
    uniquification so their prompt tokens stay unambiguous."""
    character_names = {bible.name for bible in character_bibles}
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    refs: list[dict] = []

    def add(name: str, asset_id: str) -> None:
        if asset_id in seen_ids:
            return
        if name in character_names and name in seen_names:
            # Another image of a character we already reference — a second
            # named ref would make Kling render them twice. Drop it.
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
        for aid in bible.reference_asset_ids[:1]:  # one image per character
            add(bible.name, aid)
    for aid in shot_asset_ids:
        add(asset_names.get(aid) or aid, aid)
    return refs


def cap_references(refs_by_priority: list[list[dict]], limit: int) -> list[dict]:
    """Cap reference images to the provider limit by PRIORITY, never naively.

    `refs_by_priority` is a list of groups ordered most-important first (e.g.
    [characters, storyboard, anchor, props]). Groups are flattened in that
    order and truncated from the END, so the lowest-priority entries (props)
    are dropped first while characters / the 分镜图 storyboard / the
    上一场景 frame anchor survive. Order within each group is preserved.
    The live Kling o3-pro API rejects more than `limit` images (ret:1201).
    Dropped reference names are logged as a warning. Pure — no I/O."""
    flat = [ref for group in refs_by_priority for ref in group]
    if len(flat) <= limit:
        return flat
    kept, dropped = flat[:limit], flat[limit:]
    logger.warning(
        "%d reference images exceed the provider limit of %d; dropping the "
        "lowest-priority references: %s",
        len(flat), limit, ", ".join(r["name"] for r in dropped),
    )
    return kept


def voice_line(character_bibles: list[CharacterBible]) -> str:
    """One deterministic voice-direction line for the render prompt, e.g.
    'Voices: @乐乐 — cheerful bright child's voice, speaks slowly; @天天 — ...'.
    Each character's voice_rules are joined with ', '; characters without
    rules are skipped; '' when nobody has rules. Shared by the prompt-agent
    path and render_service so the same character sounds identical in every
    render instead of Kling picking a random voice."""
    parts = [
        f"@{bible.name} — {', '.join(rule.strip() for rule in rules)}"
        for bible in character_bibles
        if (rules := [r for r in bible.voice_rules if r.strip()])
    ]
    return f"Voices: {'; '.join(parts)}" if parts else ""


def enforce_render_defaults(
    spec: RenderSpec,
    *,
    named_references: list[dict],
    character_bibles: list[CharacterBible] | None = None,
) -> None:
    """Post-LLM enforcement of fields the pipeline guarantees: voice/sound on,
    every supplied reference present in reference_images, multi-shot always
    enabled (Kling 'intelligence' mode when the model wrote no storyboard),
    and the cast's voice_rules as a 'Voices:' direction — appended BEFORE the
    negative lines, and only when the prompt doesn't already carry one
    (idempotent on re-runs)."""
    spec.sound = True
    spec.keep_original_sound = True
    if not spec.multi_shot:
        spec.multi_shot = True
        spec.shot_type = "intelligence"
        spec.multi_prompt = []
    voices = voice_line(character_bibles or [])
    if voices and "Voices:" not in spec.prompt:
        spec.prompt = f"{spec.prompt} — {voices}."
    if "no subtitles" not in spec.prompt.lower():
        spec.prompt = f"{spec.prompt} — {NO_TEXT_NEGATIVE} (added in post)."
    if "no clones" not in spec.prompt.lower():
        spec.prompt = f"{spec.prompt} — {NO_CLONE_NEGATIVE}."
    present = {r.asset_id for r in spec.reference_images}
    for ref in named_references:
        if ref["asset_id"] not in present:
            present.add(ref["asset_id"])
            spec.reference_images.append(
                ReferenceImage(name=ref["name"], asset_id=ref["asset_id"])
            )
    # Priority cap to the live Kling limit: character references first, then
    # everything else in its existing order (caller refs precede shot assets in
    # collect_named_references, so shot assets are dropped first).
    limit = get_settings().atlas_video_max_refs
    if len(spec.reference_images) > limit:
        character_names = {b.name for b in (character_bibles or [])}
        character_ids = {
            aid
            for b in (character_bibles or [])
            for aid in b.reference_asset_ids[:1]
        }
        chars: list[dict] = []
        others: list[dict] = []
        for r in spec.reference_images:
            group = (
                chars
                if r.name in character_names or r.asset_id in character_ids
                else others
            )
            group.append({"name": r.name, "asset_id": r.asset_id})
        spec.reference_images = [
            ReferenceImage(**ref) for ref in cap_references([chars, others], limit)
        ]


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
    dialogue_language: str | None = None,
    style: dict | None = None,
    story: dict | None = None,
    client=None,
) -> RenderSpec:
    """`named_references` is a list of {"name": str, "asset_id": str} the model
    should reference by @name and echo into reference_images verbatim. Character
    bible reference images and the shot's asset_ids (display names supplied via
    `asset_names`) are merged in so every available image reaches Kling images[].
    `dialogue_language` controls the language of the spoken 「 」 lines; when None
    it falls back to the config default (the resolver-backed value is threaded in
    by the caller via render_service)."""
    dialogue_language = dialogue_language or get_settings().dialogue_language
    character_bibles = character_bibles or []
    named_references = collect_named_references(
        named_references=named_references or [],
        character_bibles=character_bibles,
        shot_asset_ids=list(shot.asset_ids or []),
        asset_names=asset_names or {},
    )
    aspect_ratio = aspect_ratio or get_settings().default_aspect_ratio
    style_blocks = [as_block("Project style guide", style)] if style else []
    story_blocks = (
        [as_block("Overall story and sibling scenes (keep continuity)", story)]
        if story
        else []
    )
    prompt = "\n\n".join(
        [
            as_block("Scene id", scene_id),
            as_block("Scene summary", scene_summary),
            as_block("Shot", shot),
            as_block("Aspect ratio", aspect_ratio),
            *style_blocks,
            *story_blocks,
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
    enforce_render_defaults(
        spec, named_references=named_references, character_bibles=character_bibles
    )
    return spec
