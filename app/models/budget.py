"""Run budget — the hard cost guardrail for an autonomous render chain / workflow.

Costs are relative "credits" (no real billing API on this stack): one budget row
scopes the spend of a supervised render chain (keyed by root_job_id) or an
autopilot workflow run (keyed by workflow_run_id). The supervision policy refuses
the next expensive (video) step once `spent_units` would exceed `limit_units`,
which — together with the per-attempt cap — guarantees the loop terminates.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import new_id, utcnow


class RunBudget(SQLModel, table=True):
    __tablename__ = "run_budgets"

    id: str = Field(default_factory=lambda: new_id("bud"), primary_key=True)
    project_id: str | None = Field(default=None, index=True)
    # A budget is scoped to one of these (whichever started it).
    workflow_run_id: str | None = Field(default=None, index=True)
    root_job_id: str | None = Field(default=None, index=True)
    limit_units: int = 0
    spent_units: int = 0
    status: str = "open"  # 'open' | 'exhausted' | 'stopped'
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
