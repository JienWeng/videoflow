"""Controlled, structured output for conversational scene conversion."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ConversationBrief(BaseModel):
    """Small set of knobs that constrains the dialogue planner."""

    goal: str = Field(default="", max_length=500)
    tone: str = Field(default="natural", max_length=80)
    language: str = Field(default="", max_length=80)
    relationship: str = Field(default="", max_length=500)
    emotional_beats: list[str] = Field(default_factory=list, max_length=8)
    speaker_order: list[str] = Field(default_factory=list, max_length=12)
    max_words_per_line: int = Field(default=10, ge=3, le=20)
    allow_narration: bool = False


class ConversationTurn(BaseModel):
    """One deterministic dialogue turn mapped to one existing shot."""

    shot_index: int = Field(ge=0)
    speaker: str = Field(min_length=1, max_length=80)
    line: str = Field(min_length=1, max_length=160)
    visual_action: str = Field(min_length=1, max_length=500)
    emotion: str = Field(default="natural", max_length=80)


class ConversationPlan(BaseModel):
    """The only model output accepted by the conversational conversion flow."""

    scene_summary: str = Field(min_length=1, max_length=1200)
    turns: list[ConversationTurn] = Field(default_factory=list)
    note: str = Field(default="", max_length=300)
