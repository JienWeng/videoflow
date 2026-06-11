"""Revision table: lightweight edit history for scenes and shots.

Each row stores the PREVIOUS values of only the fields a single update
changed, so reverting is "apply fields_json back through update_*".
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from app.models.base import new_id, utcnow


class Revision(SQLModel, table=True):
    __tablename__ = "revisions"

    id: str = Field(default_factory=lambda: new_id("rev"), primary_key=True)
    entity_type: str  # "scene" | "shot"
    entity_id: str = Field(index=True)
    fields_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    source: str = "edit"  # "edit" | "refine" | "revert" | "system"
    created_at: datetime = Field(default_factory=utcnow)
