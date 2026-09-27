"""Background operation table — tracks fire-and-forget long generations
(storyboard, asset generation, captions, style ingest, video generation). Distinct from
render_jobs: ops are simple asyncio tasks, not queued/reconciled work."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.models.base import new_id, utcnow


class Op(SQLModel, table=True):
    __tablename__ = "ops"

    id: str = Field(default_factory=lambda: new_id("op"), primary_key=True)
    kind: str  # storyboard | assets | caption | style_ingest | video_generation
    status: str = "running"  # running | succeeded | failed
    scene_id: str | None = None
    output_id: str | None = None
    project_id: str | None = None
    error: str | None = None
    result_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
