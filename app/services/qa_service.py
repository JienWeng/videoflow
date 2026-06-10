"""QA orchestration: extract frames, gather the render's reference images, run
the vision QA agent, persist the result.

The QA agent receives REFERENCE images first (the scene's 分镜图 + the cast's
character sheets) and then FRAMES sampled from the rendered video, so it judges
character consistency / scene continuity / lighting against what the render was
actually supposed to follow.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlmodel import Session

from app.agents.qa_agent import review_output
from app.config import get_settings
from app.models import Character, RenderJob, RenderOutput, Scene
from app.models.base import utcnow
from app.services import media

logger = logging.getLogger("videoflow.qa")

MAX_REFERENCE_IMAGES = 4


def _reference_image_paths(session: Session, job: RenderJob) -> list[str]:
    """分镜图 first, then one sheet per cast character, capped to keep tokens sane."""
    from app.services import storyboard_service

    paths: list[str] = []
    if job.scene_id:
        storyboard = storyboard_service.latest_storyboard_for_scene(session, job.scene_id)
        if storyboard and storyboard.file_path and Path(storyboard.file_path).exists():
            paths.append(storyboard.file_path)
        scene = session.get(Scene, job.scene_id)
        for cid in (scene.character_ids_json or []) if scene else []:
            char = session.get(Character, cid)
            for aid in (char.reference_asset_ids_json or [])[:1] if char else []:
                from app.models import Asset

                asset = session.get(Asset, aid)
                if asset and asset.file_path and Path(asset.file_path).exists():
                    paths.append(asset.file_path)
    return paths[:MAX_REFERENCE_IMAGES]


async def run_qa(
    session: Session, job: RenderJob, output: RenderOutput, video_path: Path
) -> RenderOutput:
    settings = get_settings()
    frames_dir = settings.outputs_dir / (job.scene_id or "misc") / f"{job.id}_frames"
    frames = await media.extract_frames(video_path, frames_dir)
    references = _reference_image_paths(session, job)

    requirements = (job.request_json or {}).get("prompt", "")
    shots = (job.request_json or {}).get("multi_prompt") or []
    if shots:
        requirements += "\nShots:\n" + "\n".join(
            f"{s.get('index', i + 1)}. {s.get('prompt', '')} ({s.get('duration')}s)"
            for i, s in enumerate(shots)
        )
    description = (
        f"Generated video at {video_path.name}. "
        f"Multi-shot={ (job.request_json or {}).get('multi_shot') }. "
        f"Sound={ (job.request_json or {}).get('sound') }."
    )
    try:
        result = await review_output(
            requirements=requirements,
            output_description=description,
            frames=[str(f) for f in frames],
            reference_images=references,
        )
    except Exception:
        logger.exception("QA failed for job %s", job.id)
        return output

    output.score = result.score
    output.notes = result.recommendation
    output.qa_json = result.model_dump()
    output.updated_at = utcnow()
    session.add(output)
    session.commit()
    session.refresh(output)
    logger.info("QA job %s -> score=%d %s", job.id, result.score, result.recommendation)
    return output
