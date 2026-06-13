"""分镜图 (storyboard contact sheet) generation.

Before a multi-shot render, generate ONE ERNIE image laid out as an NxN grid of
panels — one panel per storyboard beat — so Kling receives a reference that
locks character appearance (上相一致), scene continuity (场景连贯) and the
lighting/mood of the script (光线氛围) across every shot. The sheet is stored as
a normal Asset (type 'storyboard') and fed into reference-to-video images[].
"""

from __future__ import annotations

from sqlmodel import Session, select

from app.config import get_settings
from app.errors import ValidationFailedError
from app.models import Asset, Character, StyleGuide
from app.models.base import new_id
from app.providers.atlascloud_client import get_atlas_client
from app.providers.atlascloud_image import STORYBOARD_IMAGE_CAP, AtlasCloudImageProvider
from app.providers.polling import poll_until_terminal
from app.services import project_service, media, style_service

MIN_GRID = 2
MAX_GRID = 4

# Types that are never useful as storyboard visual reference inputs.
_EXCLUDED_ASSET_TYPES = {"video", "storyboard", "character_reference"}

# Provider hard cap: nano-banana-2/edit accepts at most this many reference
# images — sourced from the provider's declared capability metadata.
_PROVIDER_IMAGE_CAP = STORYBOARD_IMAGE_CAP


def collect_prop_reference_ids(
    *,
    scene,
    shots: list,
    assets_by_id: dict,
    already_in: set[str],
) -> list[str]:
    """Return an ordered, deduped list of asset ids to append as prop references.

    Ordering: scene-level assets first, then each shot's assets in shot order.
    Excluded types: video, storyboard, character_reference (sheets already in cast).
    Assets with no file_path are skipped (nothing to upload).
    IDs already in `already_in` are skipped.
    Total slots available = _PROVIDER_IMAGE_CAP - len(already_in); result capped.
    """
    seen: set[str] = set(already_in)
    result: list[str] = []
    remaining = _PROVIDER_IMAGE_CAP - len(already_in)
    if remaining <= 0:
        return result

    candidate_ids: list[str] = list(scene.asset_ids_json or [])
    for shot in shots:
        candidate_ids.extend(shot.asset_ids_json or [])

    for aid in candidate_ids:
        if remaining <= 0:
            break
        if aid in seen:
            continue
        asset = assets_by_id.get(aid)
        if asset is None:
            continue
        if asset.type in _EXCLUDED_ASSET_TYPES:
            seen.add(aid)
            continue
        if not asset.file_path:
            seen.add(aid)
            continue
        seen.add(aid)
        result.append(aid)
        remaining -= 1

    return result


def pick_grid(n_beats: int) -> int:
    """Smallest grid in [2, 4] whose NxN panels fit every beat."""
    for grid in range(MIN_GRID, MAX_GRID + 1):
        if n_beats <= grid * grid:
            return grid
    raise ValueError(f"{n_beats} beats exceed the {MAX_GRID}x{MAX_GRID} panel maximum")


def build_storyboard_prompt(
    *,
    beats: list[str],
    character_lines: list[str],
    setting: str,
    lighting: str,
) -> str:
    grid = pick_grid(len(beats))
    panels = "\n".join(f"Panel {i + 1}: {beat}" for i, beat in enumerate(beats))
    characters = "\n".join(f"- {line}" for line in character_lines)
    return (
        f"Storyboard contact sheet: a clean {grid}x{grid} grid of {grid * grid} "
        f"equal panels, thin white gutters, read left-to-right top-to-bottom.\n"
        f"Every panel shows the SAME characters with identical faces, outfits and "
        f"proportions, the same continuous location, and the same lighting. "
        f"Each character appears exactly once per panel unless the beat "
        f"explicitly stages multiples.\n"
        f"Characters (identical in every panel):\n{characters}\n"
        f"Location (continuous across all panels): {setting}.\n"
        f"Lighting and mood (consistent across all panels): {lighting}.\n"
        f"{panels}\n"
        f"3D cartoon style, cinematic framing per panel, ultra detailed. "
        f"No text, no captions, no panel numbers, no watermark."
    )


async def generate_storyboard(
    session: Session,
    *,
    beats: list[str],
    character_lines: list[str],
    setting: str,
    lighting: str,
    size: str = "1024x1024",
    reference_image_urls: list[str] | None = None,
    aspect_ratio: str = "1:1",
    style: StyleGuide | None = None,
    image_provider: AtlasCloudImageProvider | None = None,
) -> Asset:
    """Generate the sheet, download it, and persist a 'storyboard' Asset.

    With `reference_image_urls` (character sheets) the edit model draws the
    actual characters (真·上相一致) with panels in the video's aspect ratio;
    without, it falls back to text-to-image from descriptions alone."""
    settings = get_settings()
    settings.ensure_dirs()
    # Pass the session so image-gen params (steps/guidance/seed/size, model id)
    # are read through the settings resolver — defaults unchanged.
    provider = image_provider or AtlasCloudImageProvider(
        get_atlas_client(), session=session
    )
    prompt = build_storyboard_prompt(
        beats=beats, character_lines=character_lines, setting=setting, lighting=lighting
    )
    # Deterministic style enforcement — the project style guide text is part
    # of the prompt regardless of what the agents wrote.
    prompt = style_service.apply_style(prompt, style)

    if reference_image_urls:
        prompt = (
            "Using the attached reference images as the EXACT appearance of the "
            "characters (faces, outfits, proportions must match) and the EXACT "
            "look of any depicted props (replicate every prop reference precisely), "
            "draw: " + prompt
        )
        payload = await provider.build_reference_payload(
            prompt=prompt, images=reference_image_urls, aspect_ratio=aspect_ratio
        )
    else:
        payload = await provider.build_payload(prompt=prompt, size=size)
    job_id = await provider.submit(payload)
    result = await poll_until_terminal(
        provider, job_id,
        interval_s=settings.poll_interval_s, timeout_s=settings.poll_timeout_s,
    )

    asset_id = new_id("asset")
    dest = settings.assets_dir / f"{asset_id}.png"
    await media.download(result.output_urls[0], dest)
    asset = Asset(
        id=asset_id,
        # Stamped at creation so the row is never committed project-less (a
        # NULL-window would risk adoption into the wrong project).
        project_id=project_service.active_project_id(session),
        type="storyboard",
        name="分镜图",
        file_path=str(dest),
        description=prompt,
        tags_json=["storyboard", f"{pick_grid(len(beats))}x{pick_grid(len(beats))}"],
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


async def generate_storyboard_for_scene(
    session: Session,
    scene_id: str,
    *,
    image_provider: AtlasCloudImageProvider | None = None,
) -> Asset:
    """Generalised entry point: beats come from the scene's stored shots, the
    character identity lines from its cast's bibles, setting/lighting from the
    scene itself. The resulting asset is linked back via metadata scene_id."""
    from app.services import scene_service

    scene = scene_service.get_scene(session, scene_id)
    shots = scene_service.list_shots(session, scene_id)
    if not shots:
        raise ValidationFailedError(
            f"scene {scene_id} has no shots — generate shots before the storyboard"
        )

    from app.providers.url_resolver import AtlasCloudUploadResolver

    # Style guide reference assets come FIRST so they anchor the look, then the
    # cast's reference sheets lock character appearance.
    style = style_service.get_style(session)
    character_lines = []
    reference_ids: list[str] = list((style.reference_asset_ids_json or []) if style else [])
    for cid in scene.character_ids_json or []:
        char = session.get(Character, cid)
        if not char:
            continue
        if char.appearance:
            character_lines.append(f"{char.name}: {char.appearance}")
        reference_ids.extend((char.reference_asset_ids_json or [])[:1])
    seen: set[str] = set()
    reference_ids = [i for i in reference_ids if not (i in seen or seen.add(i))]

    # Collect prop/asset images from the scene and its shots (excluding types
    # already captured via cast sheets or unsuitable for visual reference).
    all_assets_by_id: dict[str, Asset] = {}
    candidate_ids = list(scene.asset_ids_json or [])
    for shot in shots:
        candidate_ids.extend(shot.asset_ids_json or [])
    for aid in candidate_ids:
        asset_row = session.get(Asset, aid)
        if asset_row is not None:
            all_assets_by_id[aid] = asset_row

    prop_ids = collect_prop_reference_ids(
        scene=scene,
        shots=shots,
        assets_by_id=all_assets_by_id,
        already_in=set(reference_ids),
    )
    reference_ids.extend(prop_ids)

    resolver = AtlasCloudUploadResolver(session, get_atlas_client())
    reference_urls = await resolver.resolve(reference_ids) if reference_ids else []

    scene_json = scene.scene_json or {}
    asset = await generate_storyboard(
        session,
        beats=[s.prompt for s in shots],
        character_lines=character_lines,
        setting=scene_json.get("setting") or scene.summary,
        lighting=scene_json.get("lighting")
        or "consistent lighting and mood matching the scene across all panels",
        reference_image_urls=reference_urls,
        aspect_ratio=scene.aspect_ratio or "1:1",
        style=style,
        image_provider=image_provider,
    )
    asset.name = f"分镜图 {scene.title}"
    asset.project_id = scene.project_id
    asset.metadata_json = {**(asset.metadata_json or {}), "scene_id": scene_id}
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def latest_storyboard_for_scene(session: Session, scene_id: str) -> Asset | None:
    rows = session.exec(
        select(Asset).where(Asset.type == "storyboard").order_by(Asset.created_at.desc())
    ).all()
    for asset in rows:
        if (asset.metadata_json or {}).get("scene_id") == scene_id:
            return asset
    return None
