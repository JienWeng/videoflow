"""Script / scene / shot generation + persistence."""

from __future__ import annotations

from sqlmodel import Session, select

from app.agents.scene_agent import generate_scene
from app.agents.script_agent import generate_script
from app.agents.shot_agent import generate_shots
from app.errors import NotFoundError
from app.models import Asset, Character, Scene, Shot
from app.models.base import new_id, utcnow
from app.schemas import CharacterBible, SceneSpec, ScriptDraft
from app.services import style_service


def character_to_bible(char: Character) -> CharacterBible:
    return CharacterBible(
        character_id=char.id,
        name=char.name,
        appearance=char.appearance,
        personality=char.personality,
        visual_rules=list(char.visual_rules_json or []),
        voice_rules=list(char.voice_rules_json or []),
        reference_asset_ids=list(char.reference_asset_ids_json or []),
    )


async def create_script(
    session: Session,
    *,
    idea: str,
    target_duration: int | None = None,
    scene_count: int | None = None,
) -> ScriptDraft:
    """Generate a script and persist each scene stub as a Scene row.

    When scene_count is set, the draft is truncated to at most that many
    scenes BEFORE persisting — this is the deterministic enforcement cap.
    """
    draft = await generate_script(idea=idea, target_duration=target_duration, scene_count=scene_count)
    if scene_count is not None and len(draft.scenes) > scene_count:
        draft = draft.model_copy(update={"scenes": draft.scenes[:scene_count]})
    for s in draft.scenes:
        scene = Scene(
            id=new_id("scene"),
            title=s.title,
            summary=s.summary,
            duration=s.suggested_duration,
        )
        # Preserve the agent's scene_id mapping for traceability.
        scene.scene_json = {"script_scene_id": s.scene_id}
        session.add(scene)
    session.commit()
    return draft


def get_scene(session: Session, scene_id: str) -> Scene:
    scene = session.get(Scene, scene_id)
    if scene is None:
        raise NotFoundError(f"scene {scene_id} not found")
    return scene


def list_scenes(session: Session) -> list[Scene]:
    return list(session.exec(select(Scene)).all())


async def expand_scene(session: Session, scene_id: str, character_ids: list[str] | None = None) -> Scene:
    """Run the scene agent and persist the full SceneSpec onto the scene row."""
    scene = get_scene(session, scene_id)
    bibles = []
    for cid in character_ids or scene.character_ids_json or []:
        char = session.get(Character, cid)
        if char:
            bibles.append(character_to_bible(char))

    spec = await generate_scene(
        scene_id=scene.id,
        title=scene.title,
        summary=scene.summary,
        suggested_duration=scene.duration,
        character_bibles=bibles,
        style=style_service.style_context(style_service.get_style(session)),
    )
    scene.title = spec.title
    scene.summary = spec.summary
    scene.duration = spec.duration
    scene.aspect_ratio = spec.aspect_ratio
    scene.character_ids_json = spec.character_ids
    scene.asset_ids_json = spec.asset_ids
    scene.scene_json = spec.model_dump()
    scene.updated_at = utcnow()
    session.add(scene)
    session.commit()
    session.refresh(scene)
    return scene


def _scene_to_spec(scene: Scene) -> SceneSpec:
    if scene.scene_json and "shots" in scene.scene_json:
        return SceneSpec.model_validate(scene.scene_json)
    return SceneSpec(
        scene_id=scene.id,
        title=scene.title,
        summary=scene.summary,
        duration=scene.duration,
        aspect_ratio=scene.aspect_ratio,
        character_ids=list(scene.character_ids_json or []),
        asset_ids=list(scene.asset_ids_json or []),
        shots=[],
    )


async def create_shots(session: Session, scene_id: str) -> list[Shot]:
    """Run the shot agent and persist Shot rows for the scene."""
    scene = get_scene(session, scene_id)
    spec = _scene_to_spec(scene)
    shot_list = await generate_shots(
        scene=spec,
        style=style_service.style_context(style_service.get_style(session)),
    )

    rows: list[Shot] = []
    for order, shot in enumerate(shot_list.shots):
        row = Shot(
            scene_id=scene.id,
            shot_order=order,
            duration=shot.duration,
            prompt=shot.prompt,
            camera=shot.camera,
            movement=shot.movement,
            asset_ids_json=shot.asset_ids,
            shot_json=shot.model_dump(),
        )
        session.add(row)
        rows.append(row)
    session.commit()
    for row in rows:
        session.refresh(row)
    return rows


def delete_shot(session: Session, shot_id: str) -> None:
    shot = session.get(Shot, shot_id)
    if shot is None:
        raise NotFoundError(f"shot {shot_id} not found")
    session.delete(shot)
    session.commit()


def delete_scene(session: Session, scene_id: str) -> int:
    """Delete a scene and its shots; render history is kept. Returns shots deleted."""
    scene = get_scene(session, scene_id)
    shots = session.exec(select(Shot).where(Shot.scene_id == scene_id)).all()
    for shot in shots:
        session.delete(shot)
    session.delete(scene)
    session.commit()
    return len(shots)


def list_shots(session: Session, scene_id: str) -> list[Shot]:
    return list(
        session.exec(select(Shot).where(Shot.scene_id == scene_id).order_by(Shot.shot_order)).all()
    )


def update_scene(
    session: Session,
    scene_id: str,
    *,
    title: str | None = None,
    summary: str | None = None,
    duration: int | None = None,
    aspect_ratio: str | None = None,
    character_ids: list[str] | None = None,
    asset_ids: list[str] | None = None,
) -> Scene:
    scene = get_scene(session, scene_id)
    if title is not None:
        scene.title = title
    if summary is not None:
        scene.summary = summary
    if duration is not None:
        scene.duration = duration
    if aspect_ratio is not None:
        scene.aspect_ratio = aspect_ratio
    if character_ids is not None:
        scene.character_ids_json = character_ids
    if asset_ids is not None:
        scene.asset_ids_json = asset_ids
    scene.updated_at = utcnow()
    session.add(scene)
    session.commit()
    session.refresh(scene)
    return scene


def update_shot(
    session: Session,
    shot_id: str,
    *,
    prompt: str | None = None,
    duration: int | None = None,
    camera: str | None = None,
    movement: str | None = None,
    asset_ids: list[str] | None = None,
    shot_order: int | None = None,
) -> Shot:
    shot = session.get(Shot, shot_id)
    if shot is None:
        raise NotFoundError(f"shot {shot_id} not found")
    if prompt is not None:
        shot.prompt = prompt
    if duration is not None:
        shot.duration = duration
    if camera is not None:
        shot.camera = camera
    if movement is not None:
        shot.movement = movement
    if asset_ids is not None:
        shot.asset_ids_json = asset_ids
    if shot_order is not None:
        shot.shot_order = shot_order
    shot.updated_at = utcnow()
    session.add(shot)
    session.commit()
    session.refresh(shot)
    return shot


def add_cast_member(session: Session, scene_id: str, character_id: str) -> Scene:
    scene = get_scene(session, scene_id)
    if session.get(Character, character_id) is None:
        raise NotFoundError(f"character {character_id} not found")
    ids = list(scene.character_ids_json or [])
    if character_id not in ids:
        scene.character_ids_json = [*ids, character_id]
        scene.updated_at = utcnow()
        session.add(scene)
        session.commit()
        session.refresh(scene)
    return scene


def remove_cast_member(session: Session, scene_id: str, character_id: str) -> Scene:
    scene = get_scene(session, scene_id)
    ids = list(scene.character_ids_json or [])
    if character_id in ids:
        scene.character_ids_json = [i for i in ids if i != character_id]
        scene.updated_at = utcnow()
        session.add(scene)
        session.commit()
        session.refresh(scene)
    return scene


def attach_shot_asset(session: Session, shot_id: str, asset_id: str) -> Shot:
    shot = session.get(Shot, shot_id)
    if shot is None:
        raise NotFoundError(f"shot {shot_id} not found")
    if session.get(Asset, asset_id) is None:
        raise NotFoundError(f"asset {asset_id} not found")
    ids = list(shot.asset_ids_json or [])
    if asset_id not in ids:
        shot.asset_ids_json = [*ids, asset_id]
        shot.updated_at = utcnow()
        session.add(shot)
        session.commit()
        session.refresh(shot)
    return shot


def detach_shot_asset(session: Session, shot_id: str, asset_id: str) -> Shot:
    shot = session.get(Shot, shot_id)
    if shot is None:
        raise NotFoundError(f"shot {shot_id} not found")
    ids = list(shot.asset_ids_json or [])
    if asset_id in ids:
        shot.asset_ids_json = [i for i in ids if i != asset_id]
        shot.updated_at = utcnow()
        session.add(shot)
        session.commit()
        session.refresh(shot)
    return shot
