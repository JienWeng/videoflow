"""Server-sent events: job-status transitions for live UI updates."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.services import event_bus

router = APIRouter(tags=["events"])

HEARTBEAT_S = 15.0


@router.get("/events")
async def events() -> StreamingResponse:
    async def stream():
        q = event_bus.subscribe()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_S)
                    yield event_bus.format_sse(event)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            event_bus.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})
