"""Event bus: subscribe/publish/unsubscribe + SSE wire format."""

from __future__ import annotations

import pytest

from app.services import event_bus


@pytest.mark.asyncio
async def test_publish_reaches_all_subscribers():
    q1, q2 = event_bus.subscribe(), event_bus.subscribe()
    try:
        event_bus.publish({"job_id": "j1", "status": "succeeded"})
        assert (await q1.get())["job_id"] == "j1"
        assert (await q2.get())["status"] == "succeeded"
    finally:
        event_bus.unsubscribe(q1)
        event_bus.unsubscribe(q2)


@pytest.mark.asyncio
async def test_unsubscribed_queue_gets_nothing():
    q = event_bus.subscribe()
    event_bus.unsubscribe(q)
    event_bus.publish({"job_id": "j2", "status": "failed"})
    assert q.empty()


def test_sse_format():
    line = event_bus.format_sse({"a": 1})
    assert line == 'data: {"a": 1}\n\n'
