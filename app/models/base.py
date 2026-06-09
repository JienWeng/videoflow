"""Shared model helpers: id generation and timestamps."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def new_id(prefix: str) -> str:
    """Short, prefixed, sortable-enough id, e.g. 'asset_3f9c1a2b'."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
