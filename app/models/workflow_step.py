"""Append-only director timeline — one row per action the director took.

Powers the UI "reasoning timeline" (each step's action + rationale + result) and
is the director's durable scratchpad on resume.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import new_id, utcnow


class WorkflowStep(SQLModel, table=True):
    __tablename__ = "workflow_steps"

    id: str = Field(default_factory=lambda: new_id("wfs"), primary_key=True)
    run_id: str = Field(index=True)
    seq: int = 0
    action: str = ""
    rationale: str = ""
    result_summary: str = ""
    created_at: datetime = Field(default_factory=utcnow)
