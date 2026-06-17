"""Budget governor — cost model + RunBudget tracking.

The autonomous director is full-auto, so there is no human to stop a runaway
loop; this module is the hard guardrail. Costs are relative "credits" resolved
from settings (text=1, vision=2, image=10, video≈30×seconds), so they can be
tuned per project without a real billing API. The supervision policy calls
`can_afford(estimate_video(...))` before every expensive step and stops when the
budget (or the per-attempt cap) is reached, keeping the best output produced.
"""

from __future__ import annotations

from sqlmodel import Session, select

from app.config import Settings, get_settings
from app.errors import NotFoundError
from app.models.base import utcnow
from app.models.budget import RunBudget
from app.providers.atlascloud_video import VIDEO_MAX_DURATION, VIDEO_MIN_DURATION
from app.services import settings_service

# kind -> the resolver/config key holding its per-call unit cost.
_KIND_KEY = {
    "text": "cost_unit_text",
    "vision": "cost_unit_vision",
    "image": "cost_unit_image",
}


def _unit(session: Session, key: str, settings: Settings) -> int:
    return int(
        settings_service.resolve(
            session, key, default=getattr(settings, key), settings=settings
        )
    )


def estimate_call(session: Session, kind: str, *, settings: Settings | None = None) -> int:
    """Estimated cost of one text / vision / image call."""
    settings = settings or get_settings()
    key = _KIND_KEY.get(kind)
    if key is None:
        raise ValueError(f"unknown cost kind '{kind}'")
    return _unit(session, key, settings)


def estimate_video(
    session: Session, duration: float, *, settings: Settings | None = None
) -> int:
    """Estimated cost of one Kling render (per-second × clamped duration)."""
    settings = settings or get_settings()
    per_s = _unit(session, "cost_unit_video_per_second", settings)
    clamped = max(VIDEO_MIN_DURATION, min(VIDEO_MAX_DURATION, int(duration)))
    return per_s * clamped


def open_run(
    session: Session,
    *,
    project_id: str | None = None,
    workflow_run_id: str | None = None,
    root_job_id: str | None = None,
    limit_units: int | None = None,
    settings: Settings | None = None,
) -> RunBudget:
    """Open (or return the existing) budget for a workflow run / render chain."""
    settings = settings or get_settings()
    existing = budget_for_run(
        session, workflow_run_id=workflow_run_id, root_job_id=root_job_id
    )
    if existing is not None:
        return existing
    if limit_units is None:
        limit_units = int(
            settings_service.resolve(
                session, "run_budget_units",
                default=settings.run_budget_units, settings=settings,
            )
        )
    row = RunBudget(
        project_id=project_id,
        workflow_run_id=workflow_run_id,
        root_job_id=root_job_id,
        limit_units=limit_units,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def get_budget(session: Session, budget_id: str) -> RunBudget:
    row = session.get(RunBudget, budget_id)
    if row is None:
        raise NotFoundError(f"budget {budget_id} not found")
    return row


def budget_for_run(
    session: Session,
    *,
    workflow_run_id: str | None = None,
    root_job_id: str | None = None,
) -> RunBudget | None:
    """The budget scoped to a workflow run or a render chain, if one exists."""
    if workflow_run_id is not None:
        return session.exec(
            select(RunBudget).where(RunBudget.workflow_run_id == workflow_run_id)
        ).first()
    if root_job_id is not None:
        return session.exec(
            select(RunBudget).where(RunBudget.root_job_id == root_job_id)
        ).first()
    return None


def charge(
    session: Session,
    budget_id: str,
    kind: str | None = None,
    *,
    units: int | None = None,
    settings: Settings | None = None,
) -> RunBudget:
    """Charge a budget by an explicit `units` or by a call `kind`. Flips the
    budget to 'exhausted' once spend reaches the limit."""
    row = get_budget(session, budget_id)
    if units is None:
        if kind is None:
            raise ValueError("charge requires kind or units")
        units = estimate_call(session, kind, settings=settings)
    row.spent_units += int(units)
    if row.spent_units >= row.limit_units and row.status == "open":
        row.status = "exhausted"
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def remaining(session: Session, budget_id: str) -> int:
    row = get_budget(session, budget_id)
    return max(0, row.limit_units - row.spent_units)


def can_afford(session: Session, budget_id: str, units: int) -> bool:
    row = get_budget(session, budget_id)
    if row.status != "open":
        return False
    return row.spent_units + int(units) <= row.limit_units
