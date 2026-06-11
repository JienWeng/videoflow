"""SQLite engine + session management via SQLModel."""

from __future__ import annotations

from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

_settings = get_settings()

# check_same_thread=False so the async app + background worker can share the engine.
engine = create_engine(
    _settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    """Create all tables. Import models for side-effect registration first."""
    from app import models  # noqa: F401  (registers tables on SQLModel.metadata)

    SQLModel.metadata.create_all(engine)
    _migrate(engine)


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


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped session."""
    with Session(engine) as session:
        yield session
