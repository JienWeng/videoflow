"""Asset planning + generation for a scene.

The asset-planner agent decides which props/backgrounds/tools the scene still
needs (honoring a free-text user instruction like "the cup looks wrong, make a
red one"); each planned asset is rendered with the ERNIE image provider, stored
as a normal Asset row (metadata scene_id links it on the graph), and appended
to the scene's asset_ids_json so the next render picks it up as a reference.
The planner also tags each asset with the shot_orders that use it, so generated
assets are auto-attached to those shots and @-mentioned in their prompts —
which the render pipeline turns into Kling named references.
"""

from __future__ import annotations

import logging
import re

from sqlmodel import Session

from app.agents.asset_planner import plan_assets
from app.config import get_settings
from app.models import Asset, Character, Scene, Shot, StyleGuide
from app.models.base import new_id, utcnow
from app.providers.atlascloud_client import get_atlas_client
from app.providers.atlascloud_image import AtlasCloudImageProvider
from app.providers.polling import poll_until_terminal
from app.providers.url_resolver import AtlasCloudUploadResolver
from app.schemas import AssetPlan, PlannedAsset
from app.services import media, scene_service, style_service

logger = logging.getLogger("videoflow.assets")

# Prefix for reference-guided asset generation (nano-banana edit model) so the
# new asset matches the project's existing look.
REFERENCE_STYLE_PREFIX = (
    "Match the visual style of the attached reference images exactly. "
)


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

    plan = await plan_assets(
        scene_summary=scene.summary,
        scene_json=scene.scene_json or {},
        existing_assets=existing,
        instruction=instruction,
        shots=[{"shot_order": s.shot_order, "prompt": s.prompt} for s in shots],
        style=style_service.style_context(style_service.get_style(session)),
    )
    # Dedup FIRST, then truncate — dropped duplicates must not consume
    # max_assets slots. Shared path, so /assets/plan and /assets/generate
    # both get the deduped view.
    deduped = dedup_planned(plan.assets, [e["name"] for e in existing])
    return AssetPlan(assets=deduped[:max_assets], reasoning=plan.reasoning)


async def generate_scene_assets(
    session: Session,
    scene_id: str,
    instruction: str = "",
    max_assets: int = 4,
    *,
    image_provider: AtlasCloudImageProvider | None = None,
) -> list[Asset]:
    """Plan the scene's missing assets, generate each as an image, register and
    link them — to the scene and to the shots the planner tagged (asset_ids_json
    plus an @Name mention in the shot prompt). Returns the created Asset rows
    ([] when the plan is empty)."""
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
    provider = image_provider or AtlasCloudImageProvider(get_atlas_client())

    # Style enforcement: the guide's text is appended to every prompt in code,
    # and reference sheets (style guide refs first, then the cast's) steer the
    # edit model so generated assets match the project look.
    style = style_service.get_style(session)
    reference_ids = collect_style_reference_ids(session, scene, style)
    reference_urls: list[str] = []
    if reference_ids:
        resolver = AtlasCloudUploadResolver(session, get_atlas_client())
        reference_urls = await resolver.resolve(reference_ids)

    created: list[Asset] = []
    for item in planned:
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
        await media.download(result.output_urls[0], dest)
        asset = Asset(
            id=asset_id,
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
    scene.asset_ids_json = [*(scene.asset_ids_json or []), *[a.id for a in created]]
    scene.updated_at = utcnow()
    session.add(scene)
    session.commit()
    for asset in created:
        session.refresh(asset)
    return created
