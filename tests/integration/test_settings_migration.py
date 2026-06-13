"""Migration contract tests for the settings foundation.

Locks in the guarded ALTERs other workstreams depend on:
- agent_settings.project_id
- render_jobs.progress / render_jobs.stage
and that the new app_settings / provider_secrets tables auto-create.
The migration must be idempotent (safe to run on an already-migrated DB).
"""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from app.database import _migrate


def _legacy_engine(tmp_path):
    """A DB that predates the new columns: build the three tables WITHOUT the
    columns _migrate is supposed to add, so the ALTERs actually fire."""
    engine = create_engine(
        f"sqlite:///{tmp_path/'legacy.db'}",
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE agent_settings ("
                "id VARCHAR PRIMARY KEY, agent VARCHAR, "
                "provider VARCHAR, model VARCHAR, updated_at DATETIME)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE render_jobs ("
                "id VARCHAR PRIMARY KEY, status VARCHAR, "
                "created_at DATETIME, updated_at DATETIME)"
            )
        )
        # The migration also touches render_outputs/scenes; create minimal ones.
        conn.execute(text("CREATE TABLE render_outputs (id VARCHAR PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE scenes (id VARCHAR PRIMARY KEY)"))
    return engine


def _cols(engine, table):
    return {c["name"] for c in inspect(engine).get_columns(table)}


def test_migrate_adds_agent_settings_project_id(tmp_path):
    engine = _legacy_engine(tmp_path)
    assert "project_id" not in _cols(engine, "agent_settings")
    _migrate(engine)
    assert "project_id" in _cols(engine, "agent_settings")


def test_migrate_adds_render_progress_and_stage(tmp_path):
    engine = _legacy_engine(tmp_path)
    _migrate(engine)
    cols = _cols(engine, "render_jobs")
    assert "progress" in cols
    assert "stage" in cols


def test_migrate_is_idempotent(tmp_path):
    engine = _legacy_engine(tmp_path)
    _migrate(engine)
    # Running again must not raise (columns already present).
    _migrate(engine)
    cols = _cols(engine, "render_jobs")
    assert "progress" in cols and "stage" in cols
