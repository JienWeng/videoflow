"""Autonomous director (autopilot) endpoints.

  POST /workflows            → start a run (idea -> finished video) and return it.
  GET  /workflows            → list runs for the active project.
  GET  /workflows/{id}       → run + director timeline + current/best output.
  POST /workflows/{id}/cancel→ stop a run (keeps whatever it produced).

Live progress rides the existing /events SSE stream (events carry workflow_id).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.models import RenderOutput
from app.models.workflow_run import WorkflowRun
from app.services import autopilot_service, project_service

router = APIRouter(prefix="/workflows", tags=["workflows"])


class WorkflowCreate(BaseModel):
    """Start an autonomous run. `config` may carry budget (units), scene_count,
    and threshold overrides; all optional."""

    idea: str
    config: dict | None = None


def _output_summary(session: Session, output_id: str | None) -> dict | None:
    if not output_id:
        return None
    out = session.get(RenderOutput, output_id)
    if out is None:
        return None
    return {
        "id": out.id,
        "video_path": out.video_path,
        "captioned_path": out.captioned_path,
        "thumbnail_path": out.thumbnail_path,
        "score": out.score,
        "selected": out.selected,
    }


@router.post("")
def create_workflow(body: WorkflowCreate, session: Session = Depends(get_session)):
    pid = project_service.active_project_id(session)
    run = autopilot_service.start_run(
        session, idea=body.idea, config=body.config, project_id=pid
    )
    return run


@router.get("")
def list_workflows(session: Session = Depends(get_session)):
    pid = project_service.active_project_id(session)
    rows = session.exec(
        select(WorkflowRun)
        .where(WorkflowRun.project_id == pid)
        .order_by(WorkflowRun.created_at.desc())  # type: ignore[attr-defined]
    ).all()
    return list(rows)


@router.get("/{run_id}")
def get_workflow(run_id: str, session: Session = Depends(get_session)):
    run = autopilot_service.get_run(session, run_id)
    steps = autopilot_service.list_steps(session, run_id)
    return {
        "run": run,
        "steps": steps,
        "output": _output_summary(
            session, run.current_output_id or run.best_output_id
        ),
    }


@router.post("/{run_id}/cancel")
def cancel_workflow(run_id: str, session: Session = Depends(get_session)):
    return autopilot_service.cancel_run(session, run_id)
