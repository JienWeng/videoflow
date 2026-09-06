"""Controlled conversational conversion for scenes and their existing shots."""

from __future__ import annotations

from sqlmodel import Session, select

from app.agents import conversation_agent
from app.errors import NotFoundError
from app.models import Character, Scene, Script, Shot
from app.schemas import ConversationBrief, ConversationPlan
from app.services import project_service, scene_service, style_service


def _word_count(text: str) -> int:
    return len(text.split())


def validate_conversation_plan(
    plan: ConversationPlan,
    *,
    shot_count: int,
    allowed_speakers: set[str],
    max_words: int,
    speaker_order: list[str] | None = None,
) -> ConversationPlan:
    """Reject model output that cannot be safely applied to this scene."""

    errors: list[str] = []
    if len(plan.turns) != shot_count:
        errors.append(f"must contain one turn per shot (expected {shot_count})")
    indexes = [turn.shot_index for turn in plan.turns]
    if indexes != list(range(shot_count)):
        errors.append("turns must use shot_index 0..N-1 in order")
    for turn in plan.turns:
        if turn.speaker not in allowed_speakers:
            errors.append(f"unknown speaker '{turn.speaker}'")
        if _word_count(turn.line) > max_words:
            errors.append(
                f"dialogue for shot {turn.shot_index} is too long (max {max_words} words)"
            )
        if any(mark in turn.line for mark in ("「", "」", '"', "\n")):
            errors.append(f"dialogue for shot {turn.shot_index} contains forbidden quoting")
        if not turn.visual_action.strip():
            errors.append(f"visual action for shot {turn.shot_index} is empty")
    if speaker_order:
        invalid_order_names = [name for name in speaker_order if name not in allowed_speakers]
        if invalid_order_names:
            errors.append(f"speaker order contains unknown names: {', '.join(invalid_order_names)}")
        else:
            for index, turn in enumerate(plan.turns):
                expected = speaker_order[index % len(speaker_order)]
                if turn.speaker != expected:
                    errors.append(
                        f"shot {index} must be spoken by '{expected}', got '{turn.speaker}'"
                    )
    if errors:
        raise ValueError("; ".join(errors))
    return plan


def _character_context(session: Session, scene: Scene) -> list[dict]:
    characters: list[dict] = []
    for character_id in scene.character_ids_json or []:
        character = session.get(Character, character_id)
        if character:
            characters.append(
                {
                    "name": character.name,
                    "personality": character.personality,
                    "appearance": character.appearance,
                    "voice_rules": list(character.voice_rules_json or []),
                }
            )
    return characters


def _allowed_speakers(characters: list[dict], brief: ConversationBrief) -> set[str]:
    allowed = {c["name"] for c in characters if c.get("name")}
    if brief.allow_narration:
        allowed.add("Narrator")
    return allowed


def _prompt_for_turn(turn, *, allowed_names: set[str]) -> str:
    visual = turn.visual_action.strip()
    if turn.speaker in allowed_names and turn.speaker != "Narrator":
        if not visual.startswith((turn.speaker, f"@{turn.speaker}")):
            visual = f"@{turn.speaker} {visual}"
    return f"{visual}. {turn.speaker} says, 「{turn.line.strip()}」"


async def convert_scenes_to_conversational(
    session: Session,
    *,
    scene_ids: list[str] | None = None,
    instruction: str = "",
    include_shots: bool = True,
    brief: ConversationBrief | None = None,
    preview: bool = False,
) -> dict:
    """Plan and optionally apply a validated conversational rewrite."""

    brief = brief or ConversationBrief()
    if instruction.strip() and not brief.goal:
        brief = brief.model_copy(update={"goal": instruction.strip()[:500]})
    project_id = project_service.active_project_id(session)
    query = select(Scene).where(Scene.project_id == project_id)
    if scene_ids:
        query = query.where(Scene.id.in_(scene_ids))
    selected = list(session.exec(query).all())
    results: list[dict] = []

    for scene in selected:
        shots = list(
            session.exec(
                select(Shot).where(Shot.scene_id == scene.id).order_by(Shot.shot_order)
            ).all()
        )
        characters = _character_context(session, scene)
        allowed = _allowed_speakers(characters, brief)
        result = {
            "scene_id": scene.id,
            "status": "planned" if preview else "applied",
            "error": None,
            "scene_before": {"title": scene.title, "summary": scene.summary},
            "scene_after": None,
            "shot_count": len(shots) if include_shots else 0,
            "shot_failures": [],
            "shots": [],
        }
        if not include_shots:
            result["status"] = "skipped"
            result["error"] = "shot conversion is disabled; no conversational changes were applied"
            result["scene_after"] = result["scene_before"]
            results.append(result)
            continue
        if not shots:
            result["status"] = "skipped"
            result["error"] = "scene has no shots; generate shots before conversion"
            results.append(result)
            continue
        if not allowed:
            result["status"] = "skipped"
            result["error"] = "assign at least one character before conversion"
            results.append(result)
            continue

        plan = await conversation_agent.plan_conversation(
            scene={"title": scene.title, "summary": scene.summary, "duration": scene.duration},
            shots=[
                {
                    "shot_index": index,
                    "prompt": shot.prompt,
                    "camera": shot.camera,
                    "movement": shot.movement,
                    "duration": shot.duration,
                }
                for index, shot in enumerate(shots)
            ],
            characters=characters,
            brief=brief,
            style=style_service.style_context(style_service.get_style(session)),
            story=scene_service.story_context(session, scene),
        )
        try:
            validate_conversation_plan(
                plan,
                shot_count=len(shots),
                allowed_speakers=allowed,
                max_words=brief.max_words_per_line,
                speaker_order=brief.speaker_order,
            )
        except ValueError as exc:
            result["status"] = "rejected"
            result["error"] = str(exc)
            results.append(result)
            continue

        result["scene_after"] = {
            "title": scene.title,
            "summary": plan.scene_summary,
        }
        for shot, turn in zip(shots, plan.turns):
            result["shots"].append(
                {
                    "shot_id": shot.id,
                    "speaker": turn.speaker,
                    "line": turn.line,
                    "before": shot.prompt,
                    "after": _prompt_for_turn(turn, allowed_names=allowed),
                }
            )
        if not preview:
            scene_service.update_scene(
                session, scene.id, source="conversation", summary=plan.scene_summary
            )
            for shot, turn in zip(shots, plan.turns):
                scene_service.update_shot(
                    session,
                    shot.id,
                    source="conversation",
                    prompt=_prompt_for_turn(turn, allowed_names=allowed),
                )
            if scene.script_id:
                script = session.get(Script, scene.script_id)
                if script is not None:
                    draft = dict(script.draft_json or {})
                    draft["conversation_profile"] = {
                        **brief.model_dump(),
                        "instruction": instruction,
                        "status": "applied",
                    }
                    script.draft_json = draft
                    session.add(script)
                    session.commit()
        results.append(result)

    applied = sum(
        1 + len(result["shots"])
        for result in results
        if result["status"] in {"planned", "applied"}
    )
    return {
        "preview": preview,
        "converted": applied,
        "results": results,
        "brief": brief.model_dump(),
    }
