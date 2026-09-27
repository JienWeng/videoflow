"""High-level video generation orchestration for the simple Create flow."""

from __future__ import annotations

from collections.abc import Callable

from sqlmodel import Session

from app.schemas import ConversationBrief
from app.services import (
    project_service,
    refine_service,
    render_service,
    scene_service,
    storyboard_service,
    style_service,
)

STYLE_PRESETS = {
    "2d-picture-book": {
        "name": "2D picture book",
        "style_prompt": "warm 2D children's picture-book illustration, clean shapes, expressive faces",
        "palette": "soft pastel colors",
        "lighting": "gentle even lighting",
        "audience": "children aged 5 to 9",
        "tone": "warm and playful",
    },
    "cinematic": {
        "name": "Cinematic",
        "style_prompt": "cinematic illustrated animation, clear visual storytelling, expressive character acting",
        "palette": "cohesive cinematic color grade",
        "lighting": "motivated cinematic lighting",
        "audience": "general audience",
        "tone": "focused and emotional",
    },
}


def _apply_style_preset(session: Session, preset: str) -> None:
    """Create a default style guide only when the project has no style yet."""
    if style_service.get_style(session) is not None:
        return
    fields = STYLE_PRESETS.get(preset, STYLE_PRESETS["2d-picture-book"])
    style_service.upsert_style(session, **fields)


async def generate_video(
    session: Session,
    *,
    idea: str,
    target_duration: int | None = None,
    scene_count: int | None = None,
    style: str = "2d-picture-book",
    aspect_ratio: str = "9:16",
    language: str = "English",
    conversation_mode: str = "dialogue",
    instruction: str = "",
    on_stage: Callable[[str], None] | None = None,
) -> dict:
    """Run the user-facing video pipeline and return inspectable IDs.

    Every stage writes through the existing service boundary. A failure leaves
    all completed intermediate rows available in the advanced workspace.
    """
    _apply_style_preset(session, style)
    stages: list[str] = []
    existing_style = style_service.get_style(session)
    generation_brief = {
        "language": language,
        "instruction": instruction.strip(),
        "effective_style": style_service.style_context(existing_style),
        "aspect_ratio": aspect_ratio,
        "conversation_mode": "dialogue",
    }

    def complete(stage: str) -> None:
        stages.append(stage)
        if on_stage:
            on_stage(stage)

    script, _draft = await scene_service.create_script(
        session,
        idea=idea,
        target_duration=target_duration,
        scene_count=scene_count,
        generation_brief=generation_brief,
    )
    complete("story")

    scenes = [s for s in scene_service.list_scenes(session) if s.script_id == script.id]
    for scene in scenes:
        scene.aspect_ratio = aspect_ratio
        session.add(scene)
    session.commit()

    for scene in scenes:
        await scene_service.expand_scene(session, scene.id)
        scene.aspect_ratio = aspect_ratio
        session.add(scene)
        session.commit()
        await scene_service.create_shots(session, scene.id, auto_assets=True)
    complete("scenes")
    complete("shots")

    if conversation_mode == "dialogue":
        await refine_service.convert_scenes_to_conversational(
            session,
            scene_ids=[s.id for s in scenes],
            include_shots=True,
            instruction=instruction,
            brief=ConversationBrief(
                goal=instruction[:500],
                tone="natural",
                language=language,
                max_words_per_line=10,
                allow_narration=False,
            ),
        )
        complete("dialogue")

    render_job_ids: list[str] = []
    for scene in scenes:
        await storyboard_service.generate_storyboard_for_scene(session, scene.id)
    complete("visuals")
    for scene in scenes:
        job = await render_service.render_scene(
            session, scene.id, generation_brief=generation_brief
        )
        render_job_ids.append(job.id)
    complete("render")

    return {
        "project_id": project_service.active_project_id(session),
        "script_id": script.id,
        "scene_ids": [s.id for s in scenes],
        "render_job_ids": render_job_ids,
        "stages": stages,
        "status": "rendering",
    }
