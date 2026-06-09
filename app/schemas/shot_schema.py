"""Shot-list wrapper.

instructor (and most structured-output APIs) cannot return a bare JSON array as
the root response — they require a single object. `ShotList` is that wrapper.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.scene_schema import ShotSpec


class ShotList(BaseModel):
    scene_id: str
    shots: list[ShotSpec] = Field(default_factory=list)
