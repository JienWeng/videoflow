"""Shared literal types for wire schemas."""

from __future__ import annotations

from typing import Literal

AspectRatio = Literal["16:9", "9:16", "1:1"]

# Canonical asset vocabulary — ONE source of truth shared by the upload dropdown,
# the recogniser/planner outputs, and the library type filter. Keep this list and
# the frontend ASSET_TYPES in app/api/assets list/sync. Rows with any historical
# value outside this set are treated as "other" by the filter, never rewritten.
AssetType = Literal[
    "prop",
    "background",
    "character_reference",
    "storyboard",
    "video",
    "effect",
    "tool",
    "other",
]

#: Tuple form for runtime iteration (e.g. building filter chips / validating input).
ASSET_TYPES: tuple[str, ...] = (
    "prop",
    "background",
    "character_reference",
    "storyboard",
    "video",
    "effect",
    "tool",
    "other",
)
