"""Background processing of a render job: poll -> download -> output -> QA."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlmodel import Session

from app.config import get_settings
from app.database import engine
from app.models import Asset, RenderJob, RenderOutput, RenderStatus
from app.models.base import utcnow
from app.providers.atlascloud_video import AtlasCloudVideoProvider
from app.providers.polling import humanize_provider_error, poll_until_terminal
from app.services import event_bus, media

logger = logging.getLogger("videoflow.poll")


# Lifecycle stages, each with a user-facing progress label. `stage` is the stable
# machine key (the UI can switch on it); `progress` is the human label.
_STAGE_LABELS: dict[str, str] = {
    "submitted": "Submitted to the video model…",
    "generating": "Generating video…",
    "downloading": "Downloading the finished video…",
    "qa": "Reviewing quality…",
    "done": "Done",
    "failed": "Failed",
}


def _set_stage(session: Session, job: RenderJob, stage: str) -> None:
    """Persist a lifecycle stage + its human progress label and publish it so the
    UI's SSE stream reflects where the render is."""
    job.stage = stage
    job.progress = _STAGE_LABELS.get(stage, stage)
    job.updated_at = utcnow()
    session.add(job)
    session.commit()
    event_bus.publish(
        {"job_id": job.id, "status": job.status.value, "stage": stage,
         "progress": job.progress}
    )


async def process_job(job_id: str) -> None:
    settings = get_settings()
    with Session(engine) as session:
        job = session.get(RenderJob, job_id)
        if job is None:
            logger.warning("process_job: job %s not found", job_id)
            return
        if job.provider_job_id is None:
            _fail(session, job, "no provider_job_id")
            return

        job.status = RenderStatus.running
        session.add(job)
        session.commit()
        event_bus.publish({"job_id": job.id, "status": "running"})
        _set_stage(session, job, "generating")

        if job.provider == "openrouter":
            from app.providers.openrouter_video import OpenRouterVideoProvider

            provider = OpenRouterVideoProvider()
        else:
            provider = AtlasCloudVideoProvider()
        try:
            result = await poll_until_terminal(
                provider, job.provider_job_id,
                interval_s=settings.poll_interval_s, timeout_s=settings.poll_timeout_s,
            )
        except Exception as exc:
            _fail(session, job, str(exc))
            return

        if not result.output_urls:
            _fail(session, job, "provider returned no outputs")
            return

        # Download the first output + poster thumbnail.
        _set_stage(session, job, "downloading")
        out_dir = settings.outputs_dir / (job.scene_id or "misc")
        video_path = out_dir / f"{job.id}.mp4"
        try:
            await media.download(result.output_urls[0], video_path)
        except Exception as exc:
            _fail(session, job, f"download failed: {exc}")
            return
        thumb_path = await _make_poster(video_path, out_dir / f"{job.id}.jpg")

        output = RenderOutput(
            render_job_id=job.id,
            video_path=str(video_path),
            thumbnail_path=str(thumb_path) if thumb_path else None,
        )
        session.add(output)
        session.commit()
        session.refresh(output)

        # Surface the render in the Assets library (reusable as a reference).
        session.add(Asset(
            project_id=job.project_id,
            type="video",
            name=f"Render {job.scene_id or job.id}",
            file_path=str(video_path),
            metadata_json={
                "render_output_id": output.id,
                "render_job_id": job.id,
                "scene_id": job.scene_id,
            },
        ))
        session.commit()

        # Run QA (best-effort) BEFORE marking the job succeeded, so that a
        # `succeeded` status guarantees QA has been attempted.
        _set_stage(session, job, "qa")
        await _run_qa_if_available(session, job, output, video_path)

        job.status = RenderStatus.succeeded
        job.response_json = result.raw
        job.updated_at = utcnow()
        session.add(job)
        session.commit()
        _set_stage(session, job, "done")
        event_bus.publish({"job_id": job.id, "status": "succeeded", "output_id": output.id})
        logger.info("job %s succeeded -> %s", job.id, video_path)


async def _make_poster(video_path: Path, dest: Path) -> Path | None:
    """A poster frame for the render. Tries a frame ~1s in (skips a black lead-in);
    falls back to the final frame when that fails (very short clips). Returns None
    only when ffmpeg is unavailable / both attempts fail."""
    poster = await media.make_thumbnail(video_path, dest)
    if poster is not None:
        return poster
    return await media.extract_last_frame(video_path, dest)


def _fail(session: Session, job: RenderJob, error: str) -> None:
    job.status = RenderStatus.failed
    job.stage = "failed"
    # Translate known provider errors into a plain-language message + suggested
    # action; keep the raw error for diagnostics. `error` stays the raw string so
    # existing callers/tests that read it are unaffected; the human label lands in
    # `progress` and the SSE event.
    human = humanize_provider_error(error)
    job.error = error
    job.progress = human["message"]
    job.updated_at = utcnow()
    session.add(job)
    session.commit()
    event_bus.publish(
        {"job_id": job.id, "status": "failed", "error": error, "stage": "failed",
         "message": human["message"], "action": human["action"],
         "code": human["code"]}
    )
    logger.error("job %s failed: %s", job.id, error)


async def _run_qa_if_available(
    session: Session, job: RenderJob, output: RenderOutput, video_path: Path
) -> None:
    """Best-effort QA: a QA crash must never strand the job (it has output)."""
    try:
        from app.services import qa_service

        await qa_service.run_qa(session, job, output, video_path)
    except Exception:
        logger.exception("QA failed for job %s; continuing without QA", job.id)
