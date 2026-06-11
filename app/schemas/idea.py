"""Idea-development schemas — raw idea -> two mature concept options."""

from __future__ import annotations

from pydantic import BaseModel, Field


class IdeaOption(BaseModel):
    title: str
    premise: str = ""  # 2-3 sentences, concrete and filmable
    hook: str = ""  # why it grabs the audience in the first seconds
    why_it_works: str = ""  # one line


class IdeaOptions(BaseModel):
    options: list[IdeaOption] = []
    recommended_index: int = Field(default=0, ge=0, le=1)
    reasoning: str = ""  # one-line why the recommended one wins
