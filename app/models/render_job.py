"""Render job table — source of truth for background poll state."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from app.models.base import new_id, utcnow


class RenderStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class RenderJob(SQLModel, table=True):
    __tablename__ = "render_jobs"

    id: str = Field(default_factory=lambda: new_id("job"), primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id")
    scene_id: str | None = Field(default=None, foreign_key="scenes.id")
    shot_id: str | None = Field(default=None, foreign_key="shots.id")
    provider: str = "atlascloud"
    model: str = ""
    provider_job_id: str | None = None
    status: RenderStatus = Field(default=RenderStatus.pending)
    # Human-readable lifecycle markers updated by poll_service as the job moves:
    # stage in {submitted, generating, downloading, qa, done, failed}; progress
    # is a short user-facing label ("Generating video…"). Columns added by the
    # Foundation migration (render_jobs.progress / render_jobs.stage).
    stage: str | None = None
    progress: str | None = None
    request_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    response_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
