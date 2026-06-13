"""Integration: project export -> import round-trip (portability).

GET /projects/{id}/export streams a zip of the project's rows + referenced media;
POST /projects/import recreates it as a NEW project, copying media and rewriting
ids/paths. Export is robust to missing files (skipped with a manifest note)."""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401
from app.database import get_session
from app.models import (
    Asset,
    Character,
    RenderJob,
    RenderOutput,
    Scene,
    Script,
    Shot,
    StyleGuide,
)


@pytest.fixture
def env(monkeypatch, tmp_path):
    storage = tmp_path / "storage"
    (storage / "assets").mkdir(parents=True)
    (storage / "outputs").mkdir(parents=True)
    # A real media file on disk for the cup asset.
    cup_file = storage / "assets" / "cup.png"
    cup_file.write_bytes(b"PNGDATA-cup")
    out_file = storage / "outputs" / "scene_1.mp4"
    out_file.write_bytes(b"MP4DATA-scene1")

    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr("app.services.poll_service.engine", engine)
    monkeypatch.setattr("app.jobs.worker.reconcile_pending", lambda: 0)

    # Point the settings storage_root at tmp_path/storage for both the app and
    # the project_service (export/import resolve media against it).
    from app.config import get_settings, invalidate_settings_cache

    invalidate_settings_cache()
    s = get_settings()
    monkeypatch.setattr(s, "storage_root", storage)

    with Session(engine) as sess:
        sess.add(Character(id="char_1", name="Grace", appearance="kind"))
        sess.add(
            Asset(
                id="asset_cup",
                name="Cup",
                type="prop",
                file_path=str(cup_file),
                character_id=None,
            )
        )
        # An asset whose file is MISSING on disk — export must skip it gracefully.
        sess.add(
            Asset(
                id="asset_ghost",
                name="Ghost",
                type="prop",
                file_path=str(storage / "assets" / "does_not_exist.png"),
            )
        )
        sess.add(
            Scene(
                id="scene_1",
                title="Meadow",
                summary="a meadow lesson",
                character_ids_json=["char_1"],
                asset_ids_json=["asset_cup"],
            )
        )
        sess.add(Shot(id="shot_1", scene_id="scene_1", prompt="wide", asset_ids_json=["asset_cup"]))
        sess.add(Script(id="script_1", title="T", summary="story"))
        sess.add(StyleGuide(id="style_1", style_prompt="watercolor"))
        sess.add(RenderJob(id="job_1", scene_id="scene_1", status="succeeded"))
        sess.add(RenderOutput(id="out_1", render_job_id="job_1", video_path=str(out_file)))
        sess.commit()

    from app.main import create_app

    app = create_app()

    def _session():
        with Session(engine) as ss:
            yield ss

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as c:
        yield c, engine, storage


def _zip_bytes(resp) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(resp.content))


def test_export_produces_zip_with_manifest_and_media(env):
    client, _engine, _storage = env
    pid = client.get("/projects/active").json()["id"]

    resp = client.get(f"/projects/{pid}/export")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/zip")

    zf = _zip_bytes(resp)
    names = set(zf.namelist())
    assert "manifest.json" in names
    manifest = json.loads(zf.read("manifest.json"))

    # Rows are serialised per table.
    assert manifest["project"]["name"] == "My project"
    assert {r["id"] for r in manifest["rows"]["characters"]} == {"char_1"}
    assert {r["id"] for r in manifest["rows"]["scenes"]} == {"scene_1"}
    assert {r["id"] for r in manifest["rows"]["shots"]} == {"shot_1"}
    assert {r["id"] for r in manifest["rows"]["scripts"]} == {"script_1"}
    assert {r["id"] for r in manifest["rows"]["style_guides"]} == {"style_1"}
    assert {r["id"] for r in manifest["rows"]["render_jobs"]} == {"job_1"}
    assert {r["id"] for r in manifest["rows"]["render_outputs"]} == {"out_1"}
    assert {r["id"] for r in manifest["rows"]["assets"]} == {"asset_cup", "asset_ghost"}

    # Present media is bundled; the missing file is recorded in the manifest note.
    media_names = [n for n in names if n.startswith("media/")]
    assert any(n.endswith("cup.png") for n in media_names)
    assert any(n.endswith("scene_1.mp4") for n in media_names)
    assert any("does_not_exist" in note for note in manifest["missing_files"])


def test_import_recreates_as_new_project_with_copied_media(env):
    client, engine, storage = env
    pid = client.get("/projects/active").json()["id"]
    export = client.get(f"/projects/{pid}/export").content

    resp = client.post(
        "/projects/import",
        files={"file": ("project.zip", export, "application/zip")},
    )
    assert resp.status_code == 200, resp.text
    new = resp.json()
    new_id = new["id"]
    assert new_id != pid
    # A fresh project with the same row counts (assets: only the one with media
    # round-trips by file; the ghost row is recreated without a usable file).
    assert new["counts"]["scenes"] == 1
    assert new["counts"]["characters"] == 1
    assert new["counts"]["scripts"] == 1

    with Session(engine) as sess:
        scenes = sess.exec(select(Scene).where(Scene.project_id == new_id)).all()
        assert len(scenes) == 1
        new_scene = scenes[0]
        assert new_scene.id != "scene_1"  # ids remapped to avoid collisions
        assert new_scene.title == "Meadow"

        # The scene's character/asset cross-references were remapped to the new ids.
        new_chars = sess.exec(
            select(Character).where(Character.project_id == new_id)
        ).all()
        assert len(new_chars) == 1
        assert new_scene.character_ids_json == [new_chars[0].id]

        new_assets = sess.exec(
            select(Asset).where(Asset.project_id == new_id)
        ).all()
        cup = next(a for a in new_assets if a.name == "Cup")
        assert new_scene.asset_ids_json == [cup.id]

        # Media copied to a path under the storage root and rewritten to it.
        assert cup.file_path is not None
        from pathlib import Path

        copied = Path(cup.file_path)
        assert copied.exists()
        assert copied.read_bytes() == b"PNGDATA-cup"
        # The copied file lives under the configured storage root.
        assert str(storage) in str(copied.resolve())

        # Shots are remapped to the new scene id.
        new_shots = sess.exec(
            select(Shot).where(Shot.scene_id == new_scene.id)
        ).all()
        assert len(new_shots) == 1
        assert new_shots[0].asset_ids_json == [cup.id]


def test_import_does_not_change_active_project(env):
    client, _engine, _storage = env
    pid = client.get("/projects/active").json()["id"]
    export = client.get(f"/projects/{pid}/export").content
    client.post(
        "/projects/import",
        files={"file": ("project.zip", export, "application/zip")},
    )
    # Importing creates an inactive project; the active project is unchanged.
    assert client.get("/projects/active").json()["id"] == pid
    assert len(client.get("/projects").json()) == 2


def test_export_unknown_project_404(env):
    client, _engine, _storage = env
    assert client.get("/projects/project_nope/export").status_code == 404


def test_import_malformed_archive_returns_422_and_no_orphan(env):
    """POST /projects/import with a valid manifest whose row is missing 'id'
    must return 422 (not 500) and leave NO new project behind."""
    client, _engine, _storage = env
    before = len(client.get("/projects").json())

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "version": 1,
                    "project": {"name": "Bad", "description": ""},
                    "rows": {"characters": [{"name": "NoId"}]},
                    "missing_files": [],
                }
            ),
        )

    resp = client.post(
        "/projects/import",
        files={"file": ("bad.zip", buf.getvalue(), "application/zip")},
    )
    assert resp.status_code == 422, resp.text
    # No orphan project was created.
    assert len(client.get("/projects").json()) == before
