"""Project StyleGuide table — the singleton style record every generation step
(image, storyboard, video) references for a consistent look."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from app.models.base import new_id, utcnow


class StyleGuide(SQLModel, table=True):
    __tablename__ = "style_guides"

    id: str = Field(default_factory=lambda: new_id("style"), primary_key=True)
    name: str = "Project style"
    style_prompt: str = ""  # the text appended to every image/video generation
    palette: str = ""       # e.g. "soft pastel, warm yellows"
    lighting: str = ""      # e.g. "bright morning sunlight"
    audience: str = ""      # e.g. "children 2-6"
    tone: str = ""          # e.g. "playful, repetitive, gentle"
    reference_asset_ids_json: list = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
