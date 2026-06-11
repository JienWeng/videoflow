"""Generic background-ops runner for long generations.

Unlike the render job queue (worker pool + provider polling + restart
reconciliation), ops are simple fire-and-track asyncio tasks: create the Op
row, run the wrapped service coroutine on its own DB session, store a
JSON-able result summary, and publish status over the event bus (SSE).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlmodel import Session, select

from app.errors import NotFoundError
from app.models import Op
from app.models.base import utcnow
from app.services import event_bus

logger = logging.getLogger("videoflow.ops")

# Keep strong references so in-flight tasks aren't garbage-collected.
_live_tasks: set[asyncio.Task] = set()

# Per-kind result summarizers: the wrapped endpoints return SQLModel rows or
# lists of rows — store ids/names/paths in result_json, never raw rows.
_SUMMARIZERS: dict[str, Callable[[object], dict]] = {
    "storyboard": lambda a: {"asset_id": a.id, "name": a.name, "file_path": a.file_path},
    "assets": lambda rows: {
        "asset_ids": [a.id for a in rows],
        "names": [a.name for a in rows],
    },
    "shots": lambda rows: {
        "shot_ids": [s.id for s in rows],
        "count": len(rows),
        "scene_id": rows[0].scene_id if rows else None,
    },
    "caption": lambda o: {"output_id": o.id, "captioned_path": o.captioned_path},
    "style_ingest": lambda s: {"style_guide_id": s.id, "name": s.name},
}


def summarize_result(kind: str, value: object) -> dict:
    """JSON-able summary of a service result for `Op.result_json`."""
    return _SUMMARIZERS[kind](value)


def _publish(op_id: str, kind: str, status: str, scene_id: str | None,
             output_id: str | None, error: str | None = None) -> None:
    event = {
        "op_id": op_id,
        "kind": kind,
        "status": status,
        "scene_id": scene_id,
        "output_id": output_id,
    }
    if error:
        event["error"] = error
    event_bus.publish(event)


def start_op(
    kind: str,
    coro_factory: Callable[[Session], Awaitable[object]],
    *,
    scene_id: str | None = None,
    output_id: str | None = None,
    summarize: Callable[[object], dict] | None = None,
) -> Op:
    """Create a running Op row, then run `coro_factory(session)` as an asyncio
    task with its own session. Engine is resolved late (`database.engine` at
    call time) so test monkeypatching of `app.database.engine` takes effect."""
    from app import database

    op = Op(kind=kind, scene_id=scene_id, output_id=output_id, status="running")
    with Session(database.engine) as session:
        session.add(op)
        session.commit()
        session.refresh(op)
    op_id = op.id
    _publish(op_id, kind, "running", scene_id, output_id)

    async def _run() -> None:
        from app import database  # late-bound for test engine monkeypatching

        result: dict = {}
        error: str | None = None
        try:
            with Session(database.engine) as session:
                value = await coro_factory(session)
            result = (summarize or _SUMMARIZERS[kind])(value)
            status = "succeeded"
        except Exception as exc:  # never propagate — the op row is the report
            logger.exception("op %s (%s) failed", op_id, kind)
            status = "failed"
            error = str(exc) or exc.__class__.__name__
        with Session(database.engine) as session:
            row = session.get(Op, op_id)
            if row is not None:
                row.status = status
                row.error = error
                row.result_json = result
                row.updated_at = utcnow()
                session.add(row)
                session.commit()
        _publish(op_id, kind, status, scene_id, output_id, error)

    task = asyncio.create_task(_run())
    _live_tasks.add(task)
    task.add_done_callback(_live_tasks.discard)
    return op


def get_op(session: Session, op_id: str) -> Op:
    op = session.get(Op, op_id)
    if op is None:
        raise NotFoundError(f"op {op_id} not found")
    return op


def list_ops(session: Session, limit: int = 50) -> list[Op]:
    stmt = select(Op).order_by(Op.created_at.desc()).limit(limit)
    return list(session.exec(stmt).all())


def reconcile_stuck_ops() -> int:
    """Fail ops left 'running' by a previous process (their asyncio tasks died
    with it — unlike render jobs, ops cannot be resumed). Returns the count."""
    from app import database

    count = 0
    with Session(database.engine) as session:
        for op in session.exec(select(Op).where(Op.status == "running")).all():
            op.status = "failed"
            op.error = "server restarted before the operation finished"
            op.updated_at = utcnow()
            session.add(op)
            count += 1
        if count:
            session.commit()
    if count:
        logger.info("reconciled %d stuck ops as failed", count)
    return count
