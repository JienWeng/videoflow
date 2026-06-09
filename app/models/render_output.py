"""Render output table — one row per produced video."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from app.models.base import new_id, utcnow


class RenderOutput(SQLModel, table=True):
    __tablename__ = "render_outputs"

    id: str = Field(default_factory=lambda: new_id("out"), primary_key=True)
    render_job_id: str = Field(foreign_key="render_jobs.id")
    video_path: str | None = None
    thumbnail_path: str | None = None
    score: int | None = None
    selected: bool = False
    notes: str = ""
    qa_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
