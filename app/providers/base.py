"""Provider abstractions shared by image and video adapters."""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel

from app.providers.url_resolver import AssetUrlResolver
from app.schemas import RenderSpec

PollStatus = Literal["pending", "running", "succeeded", "failed"]

# Raw status strings AtlasCloud may return, normalised to our PollStatus.
_TERMINAL_OK = {"completed", "succeeded", "success"}
_TERMINAL_FAIL = {"failed", "error", "canceled", "cancelled", "expired"}


def normalise_status(raw: str | None) -> PollStatus:
    if raw is None:
        return "pending"
    s = raw.lower()
    if s in _TERMINAL_OK:
        return "succeeded"
    if s in _TERMINAL_FAIL:
        return "failed"
    if s in {"running", "processing", "in_progress", "started"}:
        return "running"
    return "pending"


class PollResult(BaseModel):
    status: PollStatus
    output_urls: list[str] = []
    error: str | None = None
    raw: dict = {}


@runtime_checkable
class ImageProvider(Protocol):
    name: str

    async def build_payload(self, *, prompt: str, n: int, size: str) -> dict: ...
    async def submit(self, payload: dict) -> str: ...
    async def poll(self, job_id: str) -> PollResult: ...


@runtime_checkable
class VideoProvider(Protocol):
    name: str

    async def build_payload(self, spec: RenderSpec, resolver: AssetUrlResolver) -> dict: ...
    async def submit(self, payload: dict) -> str: ...
    async def poll(self, job_id: str) -> PollResult: ...
