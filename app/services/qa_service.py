"""QA orchestration: extract frames, run the QA agent, persist the result.

Foundation note: MiniMax-Text-01 is text-only, so the agent judges against the
render request + extracted-frame count rather than true vision. Frame extraction
is wired now so a vision-capable model can be dropped in later without changing
this flow.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlmodel import Session

from app.agents.qa_agent import review_output
from app.config import get_settings
from app.models import RenderJob, RenderOutput
from app.models.base import utcnow
from app.services import media

logger = logging.getLogger("videoflow.qa")


async def run_qa(
    session: Session, job: RenderJob, output: RenderOutput, video_path: Path
) -> RenderOutput:
    settings = get_settings()
    frames_dir = settings.outputs_dir / (job.scene_id or "misc") / f"{job.id}_frames"
    frames = await media.extract_frames(video_path, frames_dir)

    requirements = (job.request_json or {}).get("prompt", "")
    description = (
        f"Generated video at {video_path.name}. "
        f"Multi-shot={ (job.request_json or {}).get('multi_shot') }. "
        f"Sound={ (job.request_json or {}).get('sound') }."
    )
    try:
        result = await review_output(
            requirements=requirements,
            output_description=description,
            frames_available=len(frames),
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
