"""Character table."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from app.models.base import new_id, utcnow


class Character(SQLModel, table=True):
    __tablename__ = "characters"

    id: str = Field(default_factory=lambda: new_id("char"), primary_key=True)
    name: str
    description: str = ""
    appearance: str = ""
    personality: str = ""
    visual_rules_json: list = Field(default_factory=list, sa_column=Column(JSON))
    voice_rules_json: list = Field(default_factory=list, sa_column=Column(JSON))
    reference_asset_ids_json: list = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
