"""Scene table."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from app.models.base import new_id, utcnow


class Scene(SQLModel, table=True):
    __tablename__ = "scenes"

    id: str = Field(default_factory=lambda: new_id("scene"), primary_key=True)
    title: str = ""
    summary: str = ""
    duration: int = 5
    aspect_ratio: str = "16:9"
    character_ids_json: list = Field(default_factory=list, sa_column=Column(JSON))
    asset_ids_json: list = Field(default_factory=list, sa_column=Column(JSON))
    scene_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
