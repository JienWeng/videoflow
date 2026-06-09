"""In-process async job queue + worker pool.

Video polls run for minutes, so they must not ride on the request lifecycle.
Jobs are enqueued by id; workers load the job, poll the provider to completion,
download outputs, and update the DB. `render_jobs.status` is the source of truth,
so a restart can reconcile in-flight jobs (see `reconcile_pending`).
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("videoflow.worker")

_queue: asyncio.Queue[str] | None = None
_workers: list[asyncio.Task] = []
_semaphore: asyncio.Semaphore | None = None


def get_queue() -> asyncio.Queue[str]:
    global _queue
    if _queue is None:
        _queue = asyncio.Queue()
    return _queue


def enqueue(job_id: str) -> None:
    get_queue().put_nowait(job_id)


async def _worker_loop(worker_id: int) -> None:
    from app.services import poll_service

    queue = get_queue()
    while True:
        job_id = await queue.get()
        try:
            assert _semaphore is not None
            async with _semaphore:
                await poll_service.process_job(job_id)
        except Exception:  # never let a worker die on one bad job
            logger.exception("worker %d: job %s failed", worker_id, job_id)
        finally:
            queue.task_done()


async def start_workers(concurrency: int, max_concurrent_polls: int) -> None:
    global _semaphore
    _semaphore = asyncio.Semaphore(max_concurrent_polls)
    get_queue()
    for i in range(concurrency):
        _workers.append(asyncio.create_task(_worker_loop(i)))
    logger.info("started %d render workers", concurrency)


async def stop_workers() -> None:
    for task in _workers:
        task.cancel()
    _workers.clear()


def reconcile_pending() -> int:
    """Re-enqueue jobs left pending/running by a previous run. Returns the count."""
    from sqlmodel import Session, select

    from app.database import engine
    from app.models import RenderJob, RenderStatus

    count = 0
    with Session(engine) as session:
        stmt = select(RenderJob).where(
            RenderJob.status.in_([RenderStatus.pending, RenderStatus.running])
        )
        for job in session.exec(stmt).all():
            enqueue(job.id)
            count += 1
    if count:
        logger.info("reconciled %d in-flight render jobs", count)
    return count
