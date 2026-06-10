"""Style agent output — the derived project style guide fields."""

from __future__ import annotations

from pydantic import BaseModel


class StyleSpec(BaseModel):
    style_prompt: str
    palette: str
    lighting: str
    audience: str
    tone: str
    reasoning: str = ""
