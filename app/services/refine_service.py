"""AI-assisted editing: an instruction becomes a partial scene/shot update."""

from __future__ import annotations

from sqlmodel import Session, select

from app.agents import refine_agent
from app.errors import NotFoundError
from app.models import Scene, Shot
from app.schemas import ConversationBrief
from app.services import (
    conversation_service,
    linking_service,
    project_service,
    scene_service,
    style_service,
)
from app.services.dialogue import DIALOGUE_RE, has_dialogue


DEFAULT_CONVERSATIONAL_INSTRUCTION = (
    "Rewrite this content in natural conversational form. Keep the same plot, "
    "characters, and continuity, but make it explicit that characters are "
    "speaking through dialogue. Preserve intent and setting."
)


def _preserve_dialogue(original: str, refined: str) -> str:
    """Every shot must speak: the captions pipeline extracts the 「」 line and
    Kling voices it, so a refine pass that drops the line would silently render
    the shot mute. If the original prompt spoke and the refined one doesn't,
    deterministically re-append the original's FIRST 「」 line. A refinement
    that carries its own 「」 line is trusted as-is. Shots only — scenes have
    no dialogue requirement."""
    if has_dialogue(original) and not has_dialogue(refined):
        match = DIALOGUE_RE.search(original)
        base = refined.rstrip()
        return (base + " " if base else "") + match.group(0)
    return refined


async def refine_scene(session: Session, scene_id: str, instruction: str) -> dict:
    """Ask the agent to rewrite the scene's editable fields, then apply them."""
    scene = scene_service.get_scene(session, scene_id)
    current = {
        "title": scene.title,
        "summary": scene.summary,
        "duration": scene.duration,
        "aspect_ratio": scene.aspect_ratio,
    }
    refinement = await refine_agent.refine_scene(
        scene=current,
        instruction=instruction,
        style=style_service.style_context(style_service.get_style(session)),
        story=scene_service.story_context(session, scene),
    )
    changes = refinement.model_dump(exclude_none=True)
    changes.pop("note", None)
    if changes:
        scene = scene_service.update_scene(session, scene_id, source="refine", **changes)
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
        style=style_service.style_context(style_service.get_style(session)),
        story=scene_service.story_context(session, parent) if parent else None,
    )
    changes = refinement.model_dump(exclude_none=True)
    changes.pop("note", None)
    if "prompt" in changes:
        changes["prompt"] = _preserve_dialogue(shot.prompt, changes["prompt"])
    if changes:
        shot = scene_service.update_shot(session, shot_id, source="refine", **changes)
    if shot.scene_id:
        # update_shot already auto-links; this also covers the no-change path.
        linking_service.auto_link_scene(session, shot.scene_id)
        session.refresh(shot)
    return {"shot": shot, "note": refinement.note}


async def convert_scenes_to_conversational(
    session: Session,
    *,
    scene_ids: list[str] | None = None,
    instruction: str = "",
    include_shots: bool = True,
    brief: ConversationBrief | None = None,
    preview: bool = False,
) -> dict:
    """Plan and optionally apply a controlled conversational rewrite."""
    return await conversation_service.convert_scenes_to_conversational(
        session,
        scene_ids=scene_ids,
        instruction=instruction or DEFAULT_CONVERSATIONAL_INSTRUCTION,
        include_shots=include_shots,
        brief=brief,
        preview=preview,
    )
