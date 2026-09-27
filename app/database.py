"""SQLite engine + session management via SQLModel."""

from __future__ import annotations

import json
from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings
from app.providers.model_ids import H3_REFERENCE_TO_VIDEO, H3_TEXT_TO_VIDEO

_settings = get_settings()

# check_same_thread=False so the async app + background worker can share the engine.
engine = create_engine(
    _settings.database_url,
    echo=False,
    # The API, worker, and local dev browser can touch SQLite concurrently.
    # Wait briefly for the writer instead of surfacing a transient
    # `database is locked` as a graph/network error.
    connect_args={"check_same_thread": False, "timeout": 30.0},
)


def init_db() -> None:
    """Create all tables. Import models for side-effect registration first."""
    from app import models  # noqa: F401  (registers tables on SQLModel.metadata)

    SQLModel.metadata.create_all(engine)
    _migrate(engine)
    _load_agent_overrides()


def _load_agent_overrides() -> None:
    """Mirror persisted per-agent LLM overrides into the in-process routing cache
    so live agent calls honour the user's Settings choices from the first request."""
    from app.services import settings_service

    with Session(engine) as session:
        settings_service.load_overrides(session)


def _migrate(target_engine) -> None:
    """Additive SQLite migrations for columns create_all won't add."""
    with target_engine.connect() as conn:
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(render_outputs)")]
        if cols and "captioned_path" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE render_outputs ADD COLUMN captioned_path VARCHAR"
            )
            conn.commit()
        if cols and "captions_json" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE render_outputs ADD COLUMN captions_json JSON"
            )
            conn.commit()
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(scenes)")]
        if cols and "script_id" not in cols:
            conn.exec_driver_sql("ALTER TABLE scenes ADD COLUMN script_id VARCHAR")
            conn.commit()
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(scenes)")]
        if cols and "scene_order" not in cols:
            conn.exec_driver_sql("ALTER TABLE scenes ADD COLUMN scene_order INTEGER")
            conn.commit()
        # Settings: per-project agent overrides (NULL = global/default override).
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(agent_settings)")]
        if cols and "project_id" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE agent_settings ADD COLUMN project_id VARCHAR"
            )
            conn.commit()
        # Render progress/stage — added here (the only file allowed to touch the
        # schema) so the render workstream can write them without editing this.
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(render_jobs)")]
        if cols and "progress" not in cols:
            conn.exec_driver_sql("ALTER TABLE render_jobs ADD COLUMN progress VARCHAR")
            conn.commit()
        if cols and "stage" not in cols:
            conn.exec_driver_sql("ALTER TABLE render_jobs ADD COLUMN stage VARCHAR")
            conn.commit()
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(ops)")]
        if cols and "project_id" not in cols:
            conn.exec_driver_sql("ALTER TABLE ops ADD COLUMN project_id VARCHAR")
            conn.commit()
        # Projects: scope columns on every project-owned table. Backfilling
        # NULLs into the default project happens lazily in
        # project_service.get_active (adopt_orphans).
        for table in (
            "characters", "assets", "scenes", "scripts", "style_guides", "render_jobs",
        ):
            cols = [r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})")]
            if cols and "project_id" not in cols:
                conn.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN project_id VARCHAR"
                )
                conn.commit()
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(characters)")]
        if cols and "sample_dialogue" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE characters ADD COLUMN sample_dialogue VARCHAR NOT NULL DEFAULT ''"
            )
            conn.commit()
        # The former AtlasCloud default was text-to-video, which ignored the
        # generated storyboard and character references. Move only rows that
        # contain that exact former default; preserve custom model selections.
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(app_settings)")]
        if cols and {"key", "value"}.issubset(cols):
            conn.exec_driver_sql(
                "UPDATE app_settings SET value = ? "
                "WHERE key = 'video_model' AND value = ?",
                (json.dumps(H3_REFERENCE_TO_VIDEO), json.dumps(H3_TEXT_TO_VIDEO)),
            )
            conn.commit()


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped session."""
    with Session(engine) as session:
        yield session
