"""Project table — the workspace boundary.

Exactly one project is ACTIVE at a time (server-side active project): every
existing list/create endpoint scopes to it implicitly, so no per-request
project parameters exist anywhere outside /projects itself.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import new_id, utcnow


class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: str = Field(default_factory=lambda: new_id("project"), primary_key=True)
    name: str = "My project"
    description: str = ""
    is_active: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
