"""Unit tests for project_service export/import (zip portability)."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401
from app.config import get_settings, invalidate_settings_cache
from app.errors import NotFoundError, ValidationFailedError
from app.models import Asset, Character, Scene, Shot, StyleGuide
from app.services import project_service


@pytest.fixture
def env(monkeypatch, tmp_path):
    storage = tmp_path / "storage"
    (storage / "assets").mkdir(parents=True)
    cup = storage / "assets" / "cup.png"
    cup.write_bytes(b"CUP")

    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    invalidate_settings_cache()
    s = get_settings()
    monkeypatch.setattr(s, "storage_root", storage)

    with Session(engine) as sess:
        active = project_service.get_active(sess)
        sess.add(Character(id="char_1", name="Grace", project_id=active.id))
        sess.add(
            Asset(
                id="asset_cup",
                name="Cup",
                type="prop",
                file_path=str(cup),
                project_id=active.id,
            )
        )
        sess.add(
            Scene(
                id="scene_1",
                title="Meadow",
                summary="x",
                project_id=active.id,
                character_ids_json=["char_1"],
                asset_ids_json=["asset_cup"],
            )
        )
        sess.add(Shot(id="shot_1", scene_id="scene_1", prompt="p"))
        sess.add(StyleGuide(id="style_1", style_prompt="wc", project_id=active.id))
        sess.commit()
        yield sess, active, storage


def test_export_bytes_round_trip(env):
    sess, active, _storage = env
    blob = project_service.export_project(sess, active.id)
    zf = zipfile.ZipFile(io.BytesIO(blob))
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["project"]["id"] == active.id
    assert {r["id"] for r in manifest["rows"]["characters"]} == {"char_1"}
    # cup.png bundled.
    assert any(n.endswith("cup.png") for n in zf.namelist())


def test_export_unknown_project_raises(env):
    sess, _active, _storage = env
    with pytest.raises(NotFoundError):
        project_service.export_project(sess, "project_nope")


def test_import_creates_new_inactive_project(env):
    sess, active, storage = env
    blob = project_service.export_project(sess, active.id)
    new = project_service.import_project(sess, blob)
    assert new.id != active.id
    assert new.is_active is False
    # Active project unchanged.
    assert project_service.get_active(sess).id == active.id

    # Remapped rows belong to the new project.
    new_scenes = sess.exec(
        select(Scene).where(Scene.project_id == new.id)
    ).all()
    assert len(new_scenes) == 1
    scene = new_scenes[0]
    assert scene.id != "scene_1"

    new_chars = sess.exec(
        select(Character).where(Character.project_id == new.id)
    ).all()
    assert scene.character_ids_json == [new_chars[0].id]

    new_assets = sess.exec(select(Asset).where(Asset.project_id == new.id)).all()
    cup = new_assets[0]
    assert scene.asset_ids_json == [cup.id]
    assert Path(cup.file_path).exists()
    assert Path(cup.file_path).read_bytes() == b"CUP"

    new_shots = sess.exec(select(Shot).where(Shot.scene_id == scene.id)).all()
    assert len(new_shots) == 1


def test_import_rejects_non_zip(env):
    sess, _active, _storage = env
    with pytest.raises(ValidationFailedError):
        project_service.import_project(sess, b"not a zip file")
