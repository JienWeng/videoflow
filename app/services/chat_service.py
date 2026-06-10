"""Guided-intent chat: build catalogs, classify, validate ids, never 500."""

from __future__ import annotations

import logging

from sqlmodel import Session, select

from app.models import Character, RenderOutput, Scene, Shot
from app.schemas import Intent, IntentAction

logger = logging.getLogger("videoflow.chat")

MIN_CONFIDENCE = 0.5


async def handle_message(session: Session, message: str) -> dict:
    from app.agents.intent_agent import classify_intent
    from app.services.caption_service import STYLES

    scenes = [{"id": s.id, "title": s.title} for s in session.exec(select(Scene)).all()]
    characters = [
        {"id": c.id, "name": c.name} for c in session.exec(select(Character)).all()
    ]
    outputs = [
        {"id": o.id, "video": o.video_path}
        for o in session.exec(select(RenderOutput)).all()
    ]

    try:
        intent = await classify_intent(
            message=message, scenes=scenes, characters=characters, outputs=outputs
        )
    except Exception:
        logger.exception("intent classification failed")
        intent = Intent(reply="Sorry — I couldn't process that. Try e.g. "
                              "「给某个场景生成分镜图」 or 'render scene X'.")

    intent = _validate(session, intent)

    return {
        "intent": intent.model_dump(),
        "options": {
            "scenes": scenes,
            "characters": characters,
            "outputs": outputs,
            "caption_styles": list(STYLES),
        },
    }


def _validate(session: Session, intent: Intent) -> Intent:
    """Drop ids that don't exist; downgrade low-confidence guesses to unknown."""
    if intent.scene_id and session.get(Scene, intent.scene_id) is None:
        intent.scene_id = None
    if intent.character_id and session.get(Character, intent.character_id) is None:
        intent.character_id = None
    if intent.shot_id and session.get(Shot, intent.shot_id) is None:
        intent.shot_id = None
    if intent.output_id and session.get(RenderOutput, intent.output_id) is None:
        intent.output_id = None
    if intent.action != IntentAction.unknown and intent.confidence < MIN_CONFIDENCE:
        intent.action = IntentAction.unknown
    return intent
