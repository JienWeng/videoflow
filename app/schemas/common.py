"""Shared literal types for wire schemas."""

from __future__ import annotations

from typing import Literal

AspectRatio = Literal["16:9", "9:16", "1:1"]

AssetType = Literal[
    "character_reference",
    "location",
    "prop",
    "video_reference",
    "audio_reference",
    "voice",
    "output_video",
]
