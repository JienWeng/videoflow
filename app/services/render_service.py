"""Render service — where AI-produced JSON (RenderSpec) meets the provider.

This is the only place agents and providers converge. It resolves reference
assets to URLs, builds the Kling payload, submits the job (so submit errors
surface immediately), persists a RenderJob, and enqueues background polling.
"""

from __future__ import annotations

import logging

from sqlmodel import Session, select

from app.agents.prompt_agent import (
    NO_CLONE_NEGATIVE,
    NO_TEXT_NEGATIVE,
    collect_named_references,
    voice_line,
)
from app.errors import NotFoundError, ValidationFailedError
from app.jobs import worker
from app.models import Asset, Character, RenderJob, RenderOutput, RenderStatus
from app.providers.atlascloud_client import get_atlas_client
from app.providers.registry import get_video_provider
from app.providers.url_resolver import AtlasCloudUploadResolver
from app.schemas import ReferenceImage, RenderSpec, StoryboardShot
from app.services.dialogue import has_dialogue

logger = logging.getLogger(__name__)


async def start_render(session: Session, spec: RenderSpec) -> RenderJob:
    provider = get_video_provider(spec)
    resolver = AtlasCloudUploadResolver(session, get_atlas_client())

    payload = await provider.build_payload(spec, resolver)
    provider_job_id = await provider.submit(payload)

    job = RenderJob(
        scene_id=spec.scene_id,
        shot_id=spec.shot_id,
        provider=spec.provider,
        model=spec.model,
        provider_job_id=provider_job_id,
        status=RenderStatus.pending,
        # Provider payload plus the originating spec, so QA-driven retries can
        # rebuild and resubmit the exact RenderSpec (asset ids, not URLs).
        request_json={**payload, "spec": spec.model_dump(mode="json")},
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    worker.enqueue(job.id)
    return job


async def render_scene(session: Session, scene_id: str) -> RenderJob:
    """Deterministic whole-scene render: stored shots become the multi-shot
    storyboard (customize, indexed), and every linked reference — characters'
    images, scene/shot assets and the scene's 分镜图 — feeds Kling images[]."""
    from app.services import scene_service, storyboard_service, style_service

    scene = scene_service.get_scene(session, scene_id)
    shots = scene_service.list_shots(session, scene_id)
    if not shots:
        raise ValidationFailedError(
            f"scene {scene_id} has no shots — generate shots before rendering"
        )
    total = sum(max(1, s.duration) for s in shots)
    if not 3 <= total <= 15:
        raise ValidationFailedError(
            f"scene duration {total}s outside the provider's 3-15s range — "
            "adjust shot durations or split the scene"
        )

    bibles = [
        scene_service.character_to_bible(c)
        for cid in scene.character_ids_json or []
        if (c := session.get(Character, cid))
    ]
    asset_ids = list(scene.asset_ids_json or [])
    for shot in shots:
        asset_ids.extend(shot.asset_ids_json or [])
    asset_names = {
        aid: a.name for aid in asset_ids
        if (a := session.get(Asset, aid)) and a.name
    }
    refs = collect_named_references(
        named_references=[],
        character_bibles=bibles,
        shot_asset_ids=asset_ids,
        asset_names=asset_names,
    )
    # Every shot is supposed to speak (one 「」 line); warn but never block.
    for shot in shots:
        if not has_dialogue(shot.prompt):
            logger.warning(
                "shot %s (order %s) of scene %s has no 「」 spoken line — "
                "it will render silent",
                shot.id, shot.shot_order, scene_id,
            )

    storyboard = storyboard_service.latest_storyboard_for_scene(session, scene_id)
    if storyboard and storyboard.id not in {r["asset_id"] for r in refs}:
        refs.append({"name": "分镜图", "asset_id": storyboard.id})

    # Deterministic voice direction from the cast's voice_rules, placed before
    # the negatives so every render of this cast uses the same voices.
    voices = voice_line(bibles)
    prompt = (
        f"{scene.summary}. "
        + ("Follow the @分镜图 storyboard panels in order for composition, scene "
           "continuity and lighting. " if storyboard else "")
        + "Spoken dialogue, clear and natural. "
        + (f"{voices}. " if voices else "")
        + "Negative: "
        f"{NO_TEXT_NEGATIVE}, no watermark, no outfit changes, no extra "
        f"characters, no distorted faces, {NO_CLONE_NEGATIVE}."
    )
    # Deterministic style enforcement on the whole-scene video prompt.
    prompt = style_service.apply_style(prompt, style_service.get_style(session))
    spec = RenderSpec(
        scene_id=scene.id,
        duration=total,
        aspect_ratio=scene.aspect_ratio,
        prompt=prompt,
        reference_images=[ReferenceImage(**r) for r in refs],
        sound=True,
        keep_original_sound=True,
        multi_shot=True,
        shot_type="customize",
        multi_prompt=[
            StoryboardShot(prompt=s.prompt, duration=max(1, s.duration)) for s in shots
        ],
    )
    return await start_render(session, spec)


# Marks (and locates) the corrective suffix appended by retry_output, so a
# retry of a retry replaces it instead of stacking suffixes.
CORRECTIONS_MARKER = "Corrections from review:"
MAX_CORRECTION_ISSUES = 5


async def retry_output(session: Session, output_id: str) -> RenderJob:
    """Submit a corrective re-render for a QA'd output.

    Rebuilds the original job's RenderSpec (stored under request_json["spec"])
    and appends the QA issues to the main prompt as
    ' Corrections from review: <issue1>; <issue2>.' — multi_prompt entries stay
    as authored. Any previous corrections suffix is stripped first, so only the
    LATEST QA issues are carried. Manual trigger only; renders cost money.
    """
    output = session.get(RenderOutput, output_id)
    if output is None:
        raise NotFoundError(f"output {output_id} not found")
    job = session.get(RenderJob, output.render_job_id)
    if job is None:
        raise NotFoundError(f"render job {output.render_job_id} not found")

    issues = [
        text for i in (output.qa_json or {}).get("issues") or []
        if (text := str(i).strip())
    ]
    if not issues:
        raise ValidationFailedError(
            f"output {output_id} has no QA issues recorded — nothing to correct"
        )

    spec_dict = (job.request_json or {}).get("spec")
    if not spec_dict:
        raise ValidationFailedError(
            f"job {job.id} did not store its render spec — cannot rebuild it for a retry"
        )
    spec = RenderSpec.model_validate(spec_dict)

    base = spec.prompt.split(CORRECTIONS_MARKER, 1)[0].rstrip()
    corrections = "; ".join(issues[:MAX_CORRECTION_ISSUES])
    spec.prompt = f"{base} {CORRECTIONS_MARKER} {corrections}."

    logger.info("corrective re-render for output %s (job %s)", output_id, job.id)
    return await start_render(session, spec)


def get_job(session: Session, job_id: str) -> RenderJob:
    job = session.get(RenderJob, job_id)
    if job is None:
        raise NotFoundError(f"render job {job_id} not found")
    return job


def list_jobs(session: Session) -> list[RenderJob]:
    return list(session.exec(select(RenderJob)).all())


def job_outputs(session: Session, job_id: str) -> list[RenderOutput]:
    return list(
        session.exec(select(RenderOutput).where(RenderOutput.render_job_id == job_id)).all()
    )
