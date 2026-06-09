"""Asset table.

`metadata_json` caches the AtlasCloud uploaded URL (key 'atlas_url') so reference
assets are not re-uploaded on every render.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from app.models.base import new_id, utcnow


class Asset(SQLModel, table=True):
    __tablename__ = "assets"

    id: str = Field(default_factory=lambda: new_id("asset"), primary_key=True)
    type: str = "prop"
    name: str = ""
    file_path: str | None = None
    tags_json: list = Field(default_factory=list, sa_column=Column(JSON))
    description: str = ""
    character_id: str | None = Field(default=None, foreign_key="characters.id")
    metadata_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
