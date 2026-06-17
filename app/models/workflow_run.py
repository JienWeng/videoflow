"""Autonomous director run state — durable + resumable (unlike Op).

One row per "idea -> finished video" run. The director loop advances off this row
(read fresh, run one step, persist), so resuming after a restart is just
re-spawning the loop over the persisted cursor. A run parks at
status='awaiting_render' while a Kling job is in flight; poll_service's terminal
callback flips it back to 'running' and re-spawns the loop.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from app.models.base import new_id, utcnow


class WorkflowRun(SQLModel, table=True):
    __tablename__ = "workflow_runs"

    id: str = Field(default_factory=lambda: new_id("wf"), primary_key=True)
    project_id: str | None = Field(default=None, index=True)
    idea: str = ""
    # autonomy_level, budget overrides, qa-threshold overrides, scene_count …
    config_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # running | awaiting_render | awaiting_approval | done | failed | cancelled
    status: str = Field(default="running", index=True)
    stage: str | None = None  # last action taken (display only)
    script_id: str | None = None
    scene_id: str | None = None
    current_job_id: str | None = Field(default=None, index=True)
    current_output_id: str | None = None
    best_output_id: str | None = None
    best_score: int | None = None
    attempt: int = 0  # number of renders produced so far for this run
    last_verdict_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    last_error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


TERMINAL_STATUSES = {"done", "failed", "cancelled"}
