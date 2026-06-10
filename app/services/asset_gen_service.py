"""Asset planning + generation for a scene.

The asset-planner agent decides which props/backgrounds/tools the scene still
needs (honoring a free-text user instruction like "the cup looks wrong, make a
red one"); each planned asset is rendered with the ERNIE image provider, stored
as a normal Asset row (metadata scene_id links it on the graph), and appended
to the scene's asset_ids_json so the next render picks it up as a reference.
"""

from __future__ import annotations

from sqlmodel import Session

from app.agents.asset_planner import plan_assets
from app.config import get_settings
from app.models import Asset
from app.models.base import new_id, utcnow
from app.providers.atlascloud_client import get_atlas_client
from app.providers.atlascloud_image import AtlasCloudImageProvider
from app.providers.polling import poll_until_terminal
from app.services import media, scene_service


async def generate_scene_assets(
    session: Session,
    scene_id: str,
    instruction: str = "",
    max_assets: int = 4,
    *,
    image_provider: AtlasCloudImageProvider | None = None,
) -> list[Asset]:
    """Plan the scene's missing assets, generate each as an image, register and
    link them. Returns the created Asset rows ([] when the plan is empty)."""
    settings = get_settings()
    settings.ensure_dirs()
    scene = scene_service.get_scene(session, scene_id)  # 404 via NotFoundError

    existing = []
    for aid in scene.asset_ids_json or []:
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
    )
    planned = plan.assets[:max_assets]
    if not planned:
        return []

    provider = image_provider or AtlasCloudImageProvider(get_atlas_client())
    created: list[Asset] = []
    for item in planned:
        payload = await provider.build_payload(prompt=item.image_prompt)
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
                "image_prompt": item.image_prompt,
            },
        )
        session.add(asset)
        created.append(asset)

    # Reassign (never mutate in place) — JSON column change detection.
    scene.asset_ids_json = [*(scene.asset_ids_json or []), *[a.id for a in created]]
    scene.updated_at = utcnow()
    session.add(scene)
    session.commit()
    for asset in created:
        session.refresh(asset)
    return created
