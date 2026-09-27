"""Migration contract tests for the settings foundation.

Locks in the guarded ALTERs other workstreams depend on:
- agent_settings.project_id
- render_jobs.progress / render_jobs.stage
and that the new app_settings / provider_secrets tables auto-create.
The migration must be idempotent (safe to run on an already-migrated DB).
"""

from __future__ import annotations

import json

from sqlalchemy import create_engine, inspect, text

from app.database import _migrate
from app.providers.model_ids import H3_REFERENCE_TO_VIDEO, H3_TEXT_TO_VIDEO


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
        conn.execute(text("CREATE TABLE ops (id VARCHAR PRIMARY KEY, kind VARCHAR)"))
        conn.execute(text("CREATE TABLE characters (id VARCHAR PRIMARY KEY, name VARCHAR)"))
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


def test_migrate_adds_operation_project_scope(tmp_path):
    engine = _legacy_engine(tmp_path)
    assert "project_id" not in _cols(engine, "ops")
    _migrate(engine)
    assert "project_id" in _cols(engine, "ops")


def test_migrate_adds_character_sample_dialogue(tmp_path):
    engine = _legacy_engine(tmp_path)
    assert "sample_dialogue" not in _cols(engine, "characters")
    _migrate(engine)
    assert "sample_dialogue" in _cols(engine, "characters")


def test_migrate_adds_scene_order(tmp_path):
    engine = _legacy_engine(tmp_path)
    assert "scene_order" not in _cols(engine, "scenes")
    _migrate(engine)
    assert "scene_order" in _cols(engine, "scenes")


def test_migrate_is_idempotent(tmp_path):
    engine = _legacy_engine(tmp_path)
    _migrate(engine)
    # Running again must not raise (columns already present).
    _migrate(engine)
    cols = _cols(engine, "render_jobs")
    assert "progress" in cols and "stage" in cols


def test_migrate_moves_only_the_former_video_default_to_reference_model(tmp_path):
    engine = _legacy_engine(tmp_path)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE app_settings (id VARCHAR PRIMARY KEY, key VARCHAR, value JSON)"
        )
        conn.execute(
            text("INSERT INTO app_settings (id, key, value) VALUES (:id, :key, :value)"),
            {
                "id": "old-default",
                "key": "video_model",
                "value": json.dumps(H3_TEXT_TO_VIDEO),
            },
        )
        conn.execute(
            text("INSERT INTO app_settings (id, key, value) VALUES (:id, :key, :value)"),
            {
                "id": "custom-model",
                "key": "video_model",
                "value": json.dumps("custom/video-model"),
            },
        )

    _migrate(engine)
    _migrate(engine)

    with engine.connect() as conn:
        models = {
            row.id: json.loads(row.value)
            for row in conn.execute(text("SELECT id, value FROM app_settings"))
        }
    assert models == {
        "old-default": H3_REFERENCE_TO_VIDEO,
        "custom-model": "custom/video-model",
    }
