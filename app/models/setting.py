"""Per-agent LLM routing overrides.

A small table that lets the user repoint any agent at a different configured
provider/model from the Settings tab, without editing `skills.py`. A row exists
only for agents the user has explicitly overridden; absence means "use the skill
default". Nulls in provider/model clear the override (revert to default).
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import new_id, utcnow


class AgentSetting(SQLModel, table=True):
    __tablename__ = "agent_settings"

    id: str = Field(default_factory=lambda: new_id("aset"), primary_key=True)
    agent: str = Field(unique=True, index=True)
    provider: str | None = None
    model: str | None = None
    updated_at: datetime = Field(default_factory=utcnow)
