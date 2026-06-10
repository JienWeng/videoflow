"""In-process pub/sub for job-status events (drives the SSE endpoint).

Consistent with the in-memory worker queue: single-process by design. A full
queue subscriber is skipped rather than blocking the publisher.
"""

from __future__ import annotations

import asyncio
import json

_subscribers: set[asyncio.Queue] = set()


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def publish(event: dict) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


def format_sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"
