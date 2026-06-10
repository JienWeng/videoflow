"""AI-assisted editing: an instruction becomes a partial scene/shot update."""

from __future__ import annotations

from sqlmodel import Session

from app.agents import refine_agent
from app.errors import NotFoundError
from app.models import Scene, Shot
from app.services import linking_service, scene_service


async def refine_scene(session: Session, scene_id: str, instruction: str) -> dict:
    """Ask the agent to rewrite the scene's editable fields, then apply them."""
    scene = scene_service.get_scene(session, scene_id)
    current = {
        "title": scene.title,
        "summary": scene.summary,
        "duration": scene.duration,
        "aspect_ratio": scene.aspect_ratio,
    }
    refinement = await refine_agent.refine_scene(scene=current, instruction=instruction)
    changes = refinement.model_dump(exclude_none=True)
    changes.pop("note", None)
    if changes:
        scene = scene_service.update_scene(session, scene_id, **changes)
    # update_scene already auto-links; this also covers the no-change path.
    linking_service.auto_link_scene(session, scene_id)
    session.refresh(scene)
    return {"scene": scene, "note": refinement.note}


async def refine_shot(session: Session, shot_id: str, instruction: str) -> dict:
    """Ask the agent to rewrite the shot's editable fields, then apply them."""
    shot = session.get(Shot, shot_id)
    if shot is None:
        raise NotFoundError(f"shot {shot_id} not found")
    parent = session.get(Scene, shot.scene_id) if shot.scene_id else None
    current = {
        "prompt": shot.prompt,
        "duration": shot.duration,
        "camera": shot.camera,
        "movement": shot.movement,
        "shot_order": shot.shot_order,
    }
    refinement = await refine_agent.refine_shot(
        shot=current,
        scene_summary=parent.summary if parent else "",
        instruction=instruction,
    )
    changes = refinement.model_dump(exclude_none=True)
    changes.pop("note", None)
    if changes:
        shot = scene_service.update_shot(session, shot_id, **changes)
    if shot.scene_id:
        # update_shot already auto-links; this also covers the no-change path.
        linking_service.auto_link_scene(session, shot.scene_id)
        session.refresh(shot)
    return {"shot": shot, "note": refinement.note}
