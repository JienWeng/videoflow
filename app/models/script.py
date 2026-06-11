"""Script table — the persisted output of the script agent (the overall story)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from app.models.base import new_id, utcnow


class Script(SQLModel, table=True):
    __tablename__ = "scripts"

    id: str = Field(default_factory=lambda: new_id("script"), primary_key=True)
    idea: str = ""  # the user's original idea text
    title: str = ""
    summary: str = ""  # the draft's overall summary/narrative
    # Full ScriptDraft dump (post scene_count truncation).
    draft_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
