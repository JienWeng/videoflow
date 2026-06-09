"""Render service — where AI-produced JSON (RenderSpec) meets the provider.

This is the only place agents and providers converge. It resolves reference
assets to URLs, builds the Kling payload, submits the job (so submit errors
surface immediately), persists a RenderJob, and enqueues background polling.
"""

from __future__ import annotations

from sqlmodel import Session, select

from app.errors import NotFoundError
from app.jobs import worker
from app.models import RenderJob, RenderOutput, RenderStatus
from app.providers.atlascloud_client import get_atlas_client
from app.providers.registry import get_video_provider
from app.providers.url_resolver import AtlasCloudUploadResolver
from app.schemas import RenderSpec


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
