"""Shot table."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from app.models.base import new_id, utcnow


class Shot(SQLModel, table=True):
    __tablename__ = "shots"

    id: str = Field(default_factory=lambda: new_id("shot"), primary_key=True)
    scene_id: str = Field(foreign_key="scenes.id")
    shot_order: int = 0
    duration: int = 5
    prompt: str = ""
    camera: str | None = None
    movement: str | None = None
    asset_ids_json: list = Field(default_factory=list, sa_column=Column(JSON))
    shot_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
