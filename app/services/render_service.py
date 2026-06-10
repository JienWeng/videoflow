"""Render service — where AI-produced JSON (RenderSpec) meets the provider.

This is the only place agents and providers converge. It resolves reference
assets to URLs, builds the Kling payload, submits the job (so submit errors
surface immediately), persists a RenderJob, and enqueues background polling.
"""

from __future__ import annotations

from sqlmodel import Session, select

from app.agents.prompt_agent import NO_TEXT_NEGATIVE, collect_named_references
from app.errors import NotFoundError, ValidationFailedError
from app.jobs import worker
from app.models import Asset, Character, RenderJob, RenderOutput, RenderStatus
from app.providers.atlascloud_client import get_atlas_client
from app.providers.registry import get_video_provider
from app.providers.url_resolver import AtlasCloudUploadResolver
from app.schemas import ReferenceImage, RenderSpec, StoryboardShot


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
        request_json=payload,
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
    from app.services import scene_service, storyboard_service

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
    storyboard = storyboard_service.latest_storyboard_for_scene(session, scene_id)
    if storyboard and storyboard.id not in {r["asset_id"] for r in refs}:
        refs.append({"name": "分镜图", "asset_id": storyboard.id})

    prompt = (
        f"{scene.summary}. "
        + ("Follow the @分镜图 storyboard panels in order for composition, scene "
           "continuity and lighting. " if storyboard else "")
        + "Spoken dialogue, clear and natural. Negative: "
        f"{NO_TEXT_NEGATIVE}, no watermark, no outfit changes, no extra "
        "characters, no distorted faces."
    )
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
