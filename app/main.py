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
    from app.services import op_service

    op_service.reconcile_stuck_ops()  # ops can't resume; mark them failed
    try:
        yield
    finally:
        # Let in-flight background ops finish writing their terminal status.
        if op_service._live_tasks:
            import asyncio

            await asyncio.gather(*op_service._live_tasks, return_exceptions=True)
        await worker.stop_workers()


def create_app() -> FastAPI:
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(title="VideoFlow", version="0.1.0", lifespan=lifespan)
    register_exception_handlers(app)

    # Local-first SvelteKit dev/preview frontend.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:4173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Media previews (assets, character refs, outputs) served straight from disk.
    settings = get_settings()
    settings.ensure_dirs()
    app.mount("/storage", StaticFiles(directory=settings.storage_root), name="storage")

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
