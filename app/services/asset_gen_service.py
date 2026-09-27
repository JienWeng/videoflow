"""Asset planning + generation for a scene.

The asset-planner agent decides which props/backgrounds/tools the scene still
needs (honoring a free-text user instruction like "the cup looks wrong, make a
red one"); each planned asset is rendered with the ERNIE image provider, stored
as a normal Asset row (metadata scene_id links it on the graph), and appended
to the scene's asset_ids_json so the next render picks it up as a reference.
The planner also tags each asset with the shot_orders that use it, so generated
assets are auto-attached to those shots and @-mentioned in their prompts —
which the render pipeline turns into Kling named references.

Cross-scene reuse: the planner also sees a compact GLOBAL asset library, and a
planned asset whose name matches a library asset is LINKED (scene + shots)
instead of regenerated — no provider spend, consistent look across scenes.
"""

from __future__ import annotations

import logging
import re

from sqlmodel import Session, select

from app.agents.asset_planner import plan_assets
from app.config import get_settings
from app.models import Asset, Character, Scene, Shot, StyleGuide
from app.models.base import new_id, utcnow
from app.providers.atlascloud_client import get_atlas_client
from app.providers.atlascloud_image import AtlasCloudImageProvider
from app.providers.polling import poll_until_terminal
from app.providers.url_resolver import AtlasCloudUploadResolver
from app.schemas import AssetPlan, PlannedAsset
from app.services import media, project_service, scene_service, style_service

logger = logging.getLogger("videoflow.assets")

# Prefix for reference-guided asset generation (nano-banana edit model) so the
# new asset matches the project's existing look.
REFERENCE_STYLE_PREFIX = (
    "Match the visual style of the attached reference images exactly. "
)

# Global library shown to the planner for cross-scene reuse: asset types that
# can't serve as image references for new scenes are excluded, and the catalog
# is capped to keep the prompt compact.
LIBRARY_EXCLUDED_TYPES = frozenset({"video", "storyboard", "character_reference", "frame"})
LIBRARY_CAP = 30


def collect_style_reference_ids(
    session: Session, scene: Scene, style: StyleGuide | None
) -> list[str]:
    """Reference sheets that lock the project look for image generation: the
    style guide's reference assets FIRST, then each cast member's first
    reference sheet (same mechanism as the storyboard), de-duplicated."""
    ids: list[str] = list((style.reference_asset_ids_json or []) if style else [])
    for cid in scene.character_ids_json or []:
        char = session.get(Character, cid)
        if char:
            ids.extend((char.reference_asset_ids_json or [])[:1])
    seen: set[str] = set()
    return [i for i in ids if not (i in seen or seen.add(i))]


def _norm_name(name: str) -> str:
    """Case-insensitive, whitespace-normalized form ("Red  Cup" == "red cup")."""
    return " ".join(name.split()).casefold()


def dedup_planned(
    assets: list[PlannedAsset], existing_names: list[str]
) -> list[PlannedAsset]:
    """Drop planned assets whose name already exists (case-insensitively, after
    whitespace normalization), preserving order. The planner prompt asks the
    LLM not to duplicate existing assets, but this is enforced in code — a
    duplicate would waste an image render and double-link on the graph."""
    existing = {_norm_name(n) for n in existing_names}
    kept: list[PlannedAsset] = []
    for asset in assets:
        if _norm_name(asset.name) in existing:
            logger.info("planner dedup: dropping duplicate asset %r", asset.name)
        else:
            kept.append(asset)
    return kept


def split_reuse(
    planned: list[PlannedAsset], library_by_name: dict
) -> tuple[list[tuple[PlannedAsset, object]], list[PlannedAsset]]:
    """Route planned assets: name-matches a global library asset (same
    case/whitespace normalization as dedup_planned) -> reuse (paired with the
    library value); novel -> generate. Order preserved in both lists."""
    index = {_norm_name(k): v for k, v in library_by_name.items()}
    to_reuse: list[tuple[PlannedAsset, object]] = []
    to_generate: list[PlannedAsset] = []
    for item in planned:
        match = index.get(_norm_name(item.name))
        if match is not None:
            to_reuse.append((item, match))
        else:
            to_generate.append(item)
    return to_reuse, to_generate


def gather_library(session: Session, exclude_ids: set[str]) -> list[Asset]:
    """Compact global asset catalog for cross-scene reuse: every asset NOT
    already linked to the scene (exclude_ids), excluding non-reusable types,
    capped at LIBRARY_CAP."""
    out: list[Asset] = []
    pid = project_service.active_project_id(session)
    # Deterministic cap: oldest assets win the LIBRARY_CAP slots.
    for asset in session.exec(
        select(Asset)
        .where(Asset.project_id == pid)
        .order_by(Asset.created_at, Asset.id)
    ):
        if asset.id in exclude_ids or asset.type in LIBRARY_EXCLUDED_TYPES:
            continue
        out.append(asset)
        if len(out) >= LIBRARY_CAP:
            break
    return out


def tag_prompt(prompt: str, name: str) -> str:
    """Mention an asset as @Name in a shot prompt, deterministically.

    Already @-tagged -> unchanged; bare name present -> first occurrence gets
    the @; otherwise append ", featuring @Name".
    """
    if f"@{name}" in prompt:
        return prompt
    # Word-boundary match so "Cup" never corrupts "Cupboard" (and an asset
    # name embedded inside a longer CJK word is appended, not spliced).
    pattern = re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)")
    if pattern.search(prompt):
        return pattern.sub(f"@{name}", prompt, count=1)
    return prompt.rstrip() + f", featuring @{name}"


async def plan_scene_assets(
    session: Session,
    scene_id: str,
    instruction: str = "",
    max_assets: int = 4,
    *,
    shots: list[Shot] | None = None,
) -> AssetPlan:
    """Plan-only: run the asset planner for a scene (no image generation, no
    DB writes) and return the truncated AssetPlan."""
    scene = scene_service.get_scene(session, scene_id)  # 404 via NotFoundError

    if shots is None:
        shots = scene_service.list_shots(session, scene_id)

    # Every asset already linked to the scene OR any of its shots: shown to the
    # planner AND used for the code-level dedup below.
    existing = []
    seen_ids: set[str] = set()
    linked_ids = list(scene.asset_ids_json or [])
    for shot in shots:
        linked_ids.extend(shot.asset_ids_json or [])
    for aid in linked_ids:
        if aid in seen_ids:
            continue
        seen_ids.add(aid)
        asset = session.get(Asset, aid)
        if asset:
            existing.append(
                {"name": asset.name, "type": asset.type, "description": asset.description}
            )

    # Cast one-liners so planned props fit the characters (e.g. child-sized
    # props for kids), plus the overall story for cross-scene continuity.
    characters = [
        {"name": c.name, "appearance": (c.appearance or "")[:160]}
        for cid in scene.character_ids_json or []
        if (c := session.get(Character, cid))
    ]

    # Global library (everything NOT already in the scene): the planner reuses
    # these by exact name instead of proposing near-duplicates.
    library_assets = gather_library(session, exclude_ids=seen_ids)

    plan = await plan_assets(
        scene_summary=scene.summary,
        scene_json=scene.scene_json or {},
        existing_assets=existing,
        library=[
            {"name": a.name, "type": a.type, "description": a.description}
            for a in library_assets
        ]
        or None,
        instruction=instruction,
        shots=[{"shot_order": s.shot_order, "prompt": s.prompt} for s in shots],
        style=style_service.style_context(style_service.get_style(session)),
        characters=characters or None,
        story=scene_service.story_context(session, scene),
    )
    # Dedup FIRST, then truncate — dropped duplicates must not consume
    # max_assets slots. Shared path, so /assets/plan and /assets/generate
    # both get the deduped view. Library matches are marked reuse=True (the
    # frontend shows "reuses existing"; generation links instead of rendering)
    # and don't consume max_assets slots — reuse is free.
    deduped = dedup_planned(plan.assets, [e["name"] for e in existing])
    library_names = {_norm_name(a.name) for a in library_assets}
    kept: list[PlannedAsset] = []
    gen_count = 0
    for asset in deduped:
        if _norm_name(asset.name) in library_names:
            kept.append(asset.model_copy(update={"reuse": True}))
        elif gen_count < max_assets:
            kept.append(asset)
            gen_count += 1
    return AssetPlan(assets=kept, reasoning=plan.reasoning)


async def generate_scene_assets(
    session: Session,
    scene_id: str,
    instruction: str = "",
    max_assets: int = 4,
    *,
    image_provider: AtlasCloudImageProvider | None = None,
) -> list[Asset]:
    """Plan the scene's missing assets; planned names that match an existing
    GLOBAL library asset are REUSED (the existing asset is linked, no image
    rendered), the rest are generated as images and registered. Both are linked
    to the scene and to the shots the planner tagged (asset_ids_json plus an
    @Name mention in the shot prompt). Returns the now-linked Asset rows —
    reused first, then newly created ([] when the plan is empty)."""
    settings = get_settings()
    settings.ensure_dirs()
    scene = scene_service.get_scene(session, scene_id)  # 404 via NotFoundError
    shots = scene_service.list_shots(session, scene_id)

    plan = await plan_scene_assets(
        session, scene_id, instruction=instruction, max_assets=max_assets, shots=shots
    )
    planned = plan.assets
    if not planned:
        return []

    shots_by_order = {s.shot_order: s for s in shots}

    # Cross-scene reuse: planned names matching a global library asset link the
    # EXISTING asset instead of regenerating a near-duplicate (same exclusion
    # set as planning, so the split mirrors what the planner saw).
    scene_linked: set[str] = set(scene.asset_ids_json or [])
    for shot in shots:
        scene_linked.update(shot.asset_ids_json or [])
    library_assets = gather_library(session, exclude_ids=scene_linked)
    to_reuse, to_generate = split_reuse(planned, {a.name: a for a in library_assets})

    reused: list[Asset] = []
    for item, existing_asset in to_reuse:
        logger.info(
            "asset reuse: linking existing %r (%s) for planned %r — no generation",
            existing_asset.name, existing_asset.id, item.name,
        )
        reused.append(existing_asset)
        # Attach to the planned shots under the EXISTING asset's canonical name.
        for order in item.shot_orders:
            shot = shots_by_order.get(order)
            if shot is None:
                continue
            ids = list(shot.asset_ids_json or [])
            if existing_asset.id not in ids:
                shot.asset_ids_json = [*ids, existing_asset.id]
            shot.prompt = tag_prompt(shot.prompt, existing_asset.name)
            shot.updated_at = utcnow()
            session.add(shot)

    from app.providers.registry import get_asset_resolver, get_image_provider_for_session
    provider = image_provider or get_image_provider_for_session(
        session, scene.project_id, atlas_client=get_atlas_client()
    )

    # Style enforcement: the guide's text is appended to every prompt in code,
    # and reference sheets (style guide refs first, then the cast's) steer the
    # edit model so generated assets match the project look.
    style = style_service.get_style(session)
    reference_ids = collect_style_reference_ids(session, scene, style)
    reference_urls: list[str] = []
    if reference_ids and to_generate:
        resolver = get_asset_resolver(session, provider.name, atlas_client=get_atlas_client())
        reference_urls = await resolver.resolve(reference_ids)

    created: list[Asset] = []
    for item in to_generate:
        styled_prompt = style_service.apply_style(item.image_prompt, style)
        if reference_urls:
            payload = await provider.build_reference_payload(
                prompt=REFERENCE_STYLE_PREFIX + styled_prompt,
                images=reference_urls,
                aspect_ratio=scene.aspect_ratio or "1:1",
            )
        else:
            payload = await provider.build_payload(prompt=styled_prompt)
        job_id = await provider.submit(payload)
        result = await poll_until_terminal(
            provider, job_id,
            interval_s=settings.poll_interval_s, timeout_s=settings.poll_timeout_s,
        )
        asset_id = new_id("asset")
        dest = settings.assets_dir / f"{asset_id}.png"
        dest = await media.download(result.output_urls[0], dest)
        asset = Asset(
            id=asset_id,
            project_id=scene.project_id,
            type=item.asset_type,
            name=item.name,
            description=item.description,
            file_path=str(dest),
            metadata_json={
                "scene_id": scene_id,
                "generated": True,
                "image_prompt": styled_prompt,
            },
        )
        session.add(asset)
        created.append(asset)

        # Auto-attach to the shots the planner tagged: link the asset id and
        # @-mention it in the shot prompt (REASSIGN JSON columns, never mutate).
        for order in item.shot_orders:
            shot = shots_by_order.get(order)
            if shot is None:
                continue
            ids = list(shot.asset_ids_json or [])
            if asset_id not in ids:
                shot.asset_ids_json = [*ids, asset_id]
            shot.prompt = tag_prompt(shot.prompt, item.name)
            shot.updated_at = utcnow()
            session.add(shot)

    # Reassign (never mutate in place) — JSON column change detection.
    # Idempotent: a reused asset already linked elsewhere is appended once.
    linked = [*reused, *created]
    scene_ids = list(scene.asset_ids_json or [])
    scene.asset_ids_json = [
        *scene_ids,
        *[a.id for a in linked if a.id not in scene_ids],
    ]
    scene.updated_at = utcnow()
    session.add(scene)
    session.commit()
    for asset in linked:
        session.refresh(asset)
    return linked
