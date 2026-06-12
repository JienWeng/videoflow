"""Asset persistence + recognition orchestration."""

from __future__ import annotations

import shutil
from pathlib import Path

from sqlmodel import Session, select

from app.agents.asset_recogniser import recognise_asset
from app.config import get_settings
from app.errors import NotFoundError
from app.models import Asset, Character, Scene, Shot
from app.models.base import new_id, utcnow
from app.models.style_guide import StyleGuide
from app.services import project_service


def save_upload(
    session: Session,
    *,
    filename: str,
    fileobj,
    asset_type: str | None = None,
    character_id: str | None = None,
) -> Asset:
    """Persist an uploaded file to storage and create an Asset row.

    If `character_id` is given, the asset is linked to that character and added to
    its reference_asset_ids — so an uploaded photo can be used directly as a video
    reference image, exactly like an AI-generated reference sheet. When linking a
    character and no type is given, the asset defaults to character_reference.
    """
    if asset_type is None:
        asset_type = "character_reference" if character_id else "prop"
    settings = get_settings()
    settings.ensure_dirs()
    asset_id = new_id("asset")
    suffix = Path(filename).suffix

    if character_id:
        char = session.get(Character, character_id)
        if char is None:
            raise NotFoundError(f"character {character_id} not found")
        dest = settings.characters_dir / character_id / f"{asset_id}{suffix}"
    else:
        char = None
        dest = settings.assets_dir / f"{asset_id}{suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)

    with dest.open("wb") as out:
        shutil.copyfileobj(fileobj, out)

    asset = Asset(
        id=asset_id,
        project_id=project_service.active_project_id(session),
        type=asset_type,
        name=Path(filename).stem,
        file_path=str(dest),
        character_id=character_id,
    )
    session.add(asset)

    if char is not None:
        ref_ids = list(char.reference_asset_ids_json or [])
        ref_ids.append(asset_id)
        char.reference_asset_ids_json = ref_ids
        session.add(char)

    session.commit()
    session.refresh(asset)
    return asset


def get_asset(session: Session, asset_id: str) -> Asset:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise NotFoundError(f"asset {asset_id} not found")
    return asset


def list_assets(session: Session) -> list[Asset]:
    pid = project_service.active_project_id(session)
    return list(session.exec(select(Asset).where(Asset.project_id == pid)).all())


def delete_asset(session: Session, asset_id: str) -> int:
    """Delete an Asset row and detach its id from all referencing rows.

    Returns the count of rows (scenes, shots, characters, style guides) that
    were updated due to the detach. The file on disk is intentionally kept.
    """
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise NotFoundError(f"asset {asset_id} not found")

    detached = 0

    # Detach from Scene.asset_ids_json
    for scene in session.exec(select(Scene)).all():
        ids = list(scene.asset_ids_json or [])
        if asset_id in ids:
            scene.asset_ids_json = [i for i in ids if i != asset_id]
            scene.updated_at = utcnow()
            session.add(scene)
            detached += 1

    # Detach from Shot.asset_ids_json
    for shot in session.exec(select(Shot)).all():
        ids = list(shot.asset_ids_json or [])
        if asset_id in ids:
            shot.asset_ids_json = [i for i in ids if i != asset_id]
            shot.updated_at = utcnow()
            session.add(shot)
            detached += 1

    # Detach from Character.reference_asset_ids_json
    for char in session.exec(select(Character)).all():
        ids = list(char.reference_asset_ids_json or [])
        if asset_id in ids:
            char.reference_asset_ids_json = [i for i in ids if i != asset_id]
            char.updated_at = utcnow()
            session.add(char)
            detached += 1

    # Detach from StyleGuide.reference_asset_ids_json
    for style in session.exec(select(StyleGuide)).all():
        ids = list(style.reference_asset_ids_json or [])
        if asset_id in ids:
            style.reference_asset_ids_json = [i for i in ids if i != asset_id]
            style.updated_at = utcnow()
            session.add(style)
            detached += 1

    session.delete(asset)
    session.commit()
    return detached


async def recognise(session: Session, asset_id: str, description: str) -> Asset:
    """Run the asset recogniser and persist its metadata onto the asset."""
    asset = get_asset(session, asset_id)
    pid = project_service.active_project_id(session)
    known = [
        c.id
        for c in session.exec(
            select(Character).where(Character.project_id == pid)
        ).all()
    ]
    meta = await recognise_asset(
        asset_id=asset.id,
        filename=asset.file_path or asset.name,
        description=description,
        known_character_ids=known,
    )
    asset.type = meta.asset_type
    asset.name = meta.name
    asset.tags_json = meta.tags
    asset.description = meta.description
    asset.character_id = meta.character_id
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset
