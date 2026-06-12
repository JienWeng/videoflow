"""Guided-intent chat: build catalogs, classify, validate ids, never 500.

State-aware: every reply carries a deterministic `project_state` snapshot
(counts + per-scene pipeline progress + ordered `next_steps`) and code-computed
`warnings` when the classified action's prerequisites are missing. The LLM
gets the same snapshot plus the recent conversation history so follow-ups
("就按你说的来") resolve.
"""

from __future__ import annotations

import logging

from sqlmodel import Session, select

from app.models import Asset, Character, RenderJob, RenderOutput, Scene, Script, Shot
from app.models.render_job import RenderStatus
from app.schemas import Intent, IntentAction

logger = logging.getLogger("videoflow.chat")

MIN_CONFIDENCE = 0.5

HISTORY_MAX_TURNS = 6
HISTORY_MAX_CHARS = 300
MAX_NEXT_STEPS = 3
MAX_WARNINGS = 2


async def handle_message(
    session: Session, message: str, history: list[dict] | None = None
) -> dict:
    from app.agents.intent_agent import classify_intent
    from app.services.caption_service import STYLES

    from app.services import project_service

    pid = project_service.active_project_id(session)
    scenes = [
        {"id": s.id, "title": s.title}
        for s in session.exec(select(Scene).where(Scene.project_id == pid)).all()
    ]
    characters = [
        {"id": c.id, "name": c.name}
        for c in session.exec(
            select(Character).where(Character.project_id == pid)
        ).all()
    ]
    outputs = [
        {"id": o.id, "video": o.video_path}
        for o in session.exec(
            select(RenderOutput)
            .join(RenderJob, RenderOutput.render_job_id == RenderJob.id)
            .where(RenderJob.project_id == pid)
        ).all()
    ]

    state = project_state(session)

    try:
        intent = await classify_intent(
            message=message,
            scenes=scenes,
            characters=characters,
            outputs=outputs,
            history=_truncate_history(history),
            state=state,
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
        "state": state,
        "warnings": _warnings(intent, state, outputs_count=len(outputs)),
    }


def project_state(session: Session) -> dict:
    """Deterministic snapshot of the active project's pipeline progress.

    {"characters": N, "has_style": bool, "scripts": N,
     "scenes": [{"id","title","expanded","has_shots","has_storyboard","rendered"}],
     "next_steps": ["Add characters (upload 2-4 photos each) — …", ...]}
    """
    from app.services import project_service, style_service

    pid = project_service.active_project_id(session)

    characters = len(
        session.exec(select(Character.id).where(Character.project_id == pid)).all()
    )
    scripts = len(
        session.exec(select(Script.id).where(Script.project_id == pid)).all()
    )
    has_style = style_service.get_style(session) is not None

    scene_rows = session.exec(select(Scene).where(Scene.project_id == pid)).all()
    shot_scene_ids = set(session.exec(select(Shot.scene_id)).all())
    storyboard_scene_ids = {
        (a.metadata_json or {}).get("scene_id")
        for a in session.exec(
            select(Asset)
            .where(Asset.project_id == pid)
            .where(Asset.type == "storyboard")
        ).all()
    }
    rendered_scene_ids = set(
        session.exec(
            select(RenderJob.scene_id)
            .where(RenderJob.project_id == pid)
            .where(RenderJob.status == RenderStatus.succeeded)
            .where(RenderJob.shot_id == None)  # noqa: E711 — scene-level renders only
        ).all()
    )

    scenes = [
        {
            "id": s.id,
            "title": s.title,
            "expanded": len(s.scene_json or {}) > 1,
            "has_shots": s.id in shot_scene_ids,
            "has_storyboard": s.id in storyboard_scene_ids,
            "rendered": s.id in rendered_scene_ids,
        }
        for s in scene_rows
    ]

    return {
        "characters": characters,
        "has_style": has_style,
        "scripts": scripts,
        "scenes": scenes,
        "next_steps": _next_steps(characters, has_style, scripts, scenes),
    }


def _next_steps(
    characters: int, has_style: bool, scripts: int, scenes: list[dict]
) -> list[str]:
    """Ordered, deterministic guidance — short bilingual lines."""
    if not scenes:
        steps = []
        if characters == 0:
            steps.append(
                "Add characters (upload 2-4 photos each) — "
                "上传角色照片（每个角色 2-4 张）"
            )
        if not has_style:
            steps.append(
                "Set a visual style — manually, or ingest one after the script "
                "exists — 设定视觉风格"
            )
        if scripts == 0:
            steps.append(
                "Write a script — tell me your story idea — "
                "写一个剧本，告诉我你的故事想法"
            )
        if not steps:
            steps.append("Generate scenes from your script — 从剧本生成场景")
        return steps

    steps: list[str] = []
    for sc in scenes:
        t = sc["title"]
        if not sc["expanded"]:
            steps.append(f"Expand scene 「{t}」 into full details — 扩展场景「{t}」")
        elif not sc["has_shots"]:
            steps.append(f"Generate shots for 「{t}」 — 为「{t}」生成分镜")
        elif not sc["has_storyboard"]:
            steps.append(f"Create the storyboard for 「{t}」 — 为「{t}」生成分镜图")
        elif not sc["rendered"]:
            steps.append(f"Render 「{t}」 — 渲染「{t}」")
        if len(steps) == MAX_NEXT_STEPS:
            return steps
    if not steps:
        steps.append(
            "All scenes rendered — add captions or start your next story — "
            "全部渲染完成，可以添加字幕或开始下一个故事"
        )
    return steps


def _warnings(intent: Intent, state: dict, outputs_count: int) -> list[str]:
    """Deterministic prerequisite warnings for the classified action (code,
    not LLM). Never blocks the action — the user may know better. Cap 2."""
    w: list[str] = []
    action = intent.action
    scenes_by_id = {s["id"]: s for s in state["scenes"]}

    if (
        action in (IntentAction.generate_script, IntentAction.generate_scenes)
        and state["characters"] == 0
    ):
        w.append(
            "No characters yet — faces won't stay consistent. Add them on the "
            "Characters page first. — 还没有角色，人脸难以保持一致，建议先上传角色照片。"
        )
    if action in (IntentAction.storyboard, IntentAction.render_scene):
        sc = scenes_by_id.get(intent.scene_id)
        if sc and not sc["has_shots"]:
            w.append(
                f"Scene 「{sc['title']}」 has no shots yet — generate shots "
                "first. — 该场景还没有分镜，请先生成分镜。"
            )
    if action == IntentAction.caption and outputs_count == 0:
        w.append(
            "Nothing rendered yet — render a scene before adding captions. — "
            "还没有渲染好的视频，请先渲染一个场景。"
        )
    if (
        action == IntentAction.style_ingest
        and state["scripts"] == 0
        and all(not s["expanded"] for s in state["scenes"])
    ):
        w.append(
            "No story to ingest from yet — write a script first. — "
            "还没有故事内容，请先写一个剧本。"
        )
    return w[:MAX_WARNINGS]


def _truncate_history(history: list[dict] | None) -> list[dict]:
    """Last 6 turns, each text capped at 300 chars; malformed turns dropped."""
    out = []
    for turn in (history or [])[-HISTORY_MAX_TURNS:]:
        if not isinstance(turn, dict):
            continue
        text = str(turn.get("text", ""))[:HISTORY_MAX_CHARS]
        if text:
            out.append({"role": turn.get("role", "user"), "text": text})
    return out


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
