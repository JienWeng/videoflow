"""Script / scene / shot generation + persistence."""

from __future__ import annotations

from sqlmodel import Session, select

from app.agents.scene_agent import generate_scene
from app.agents.script_agent import generate_script
from app.agents.shot_agent import generate_shots
from app.errors import NotFoundError
from app.models import Character, Scene, Shot
from app.models.base import new_id, utcnow
from app.schemas import CharacterBible, SceneSpec, ScriptDraft


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


async def create_script(session: Session, *, idea: str, target_duration: int | None = None) -> ScriptDraft:
    """Generate a script and persist each scene stub as a Scene row."""
    draft = await generate_script(idea=idea, target_duration=target_duration)
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
    shot_list = await generate_shots(scene=spec)

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


def list_shots(session: Session, scene_id: str) -> list[Shot]:
    return list(
        session.exec(select(Shot).where(Shot.scene_id == scene_id).order_by(Shot.shot_order)).all()
    )
