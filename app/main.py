"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.database import init_db
from app.errors import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    init_db()
    from app.jobs import worker

    await worker.start_workers(
        settings.worker_concurrency, settings.max_concurrent_polls
    )
    worker.reconcile_pending()  # re-enqueue jobs left in-flight by a prior run
    try:
        yield
    finally:
        await worker.stop_workers()


def create_app() -> FastAPI:
    app = FastAPI(title="VideoFlow", version="0.1.0", lifespan=lifespan)
    register_exception_handlers(app)

    @app.get("/health")
    async def health() -> dict:
        settings = get_settings()
        return {
            "status": "ok",
            "missing_keys": settings.missing_keys(),
            "text_model": settings.minimax_text_model,
            "image_model": settings.atlas_image_model,
            "video_model": settings.atlas_video_model,
        }

    # Routers (mounted as milestones land).
    from app.api import register_routers

    register_routers(app)
    return app


app = create_app()
