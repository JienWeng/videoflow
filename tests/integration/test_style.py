"""Integration tests for the project StyleGuide endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.database import get_session
from app.schemas import StyleSpec


class FakeLLM:
    async def generate(self, *, response_model, **kw):
        assert response_model is StyleSpec
        return StyleSpec(
            style_prompt="3D cartoon render, soft rounded shapes",
            palette="soft pastel, warm yellows",
            lighting="bright morning sunlight",
            audience="children 2-6",
            tone="playful, repetitive, gentle",
            reasoning="derived",
        )


@pytest.fixture
def client(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr("app.services.poll_service.engine", engine)
    monkeypatch.setattr("app.jobs.worker.reconcile_pending", lambda: 0)
    monkeypatch.setattr("app.agents.base.get_llm_client", lambda: FakeLLM())

    from app.models import Asset, Character, Scene

    with Session(engine) as s:
        s.add(Character(id="char_grace", name="Grace", appearance="girl in pink dress"))
        s.add(Asset(id="asset_bg", type="background", name="Meadow",
                    description="a green meadow"))
        s.add(Scene(id="scene_1", title="Meadow Lesson", summary="a sunny meadow lesson",
                    duration=6, aspect_ratio="9:16"))
        s.commit()

    from app.main import create_app

    app = create_app()

    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as c:
        yield c


def test_get_style_initially_null(client):
    resp = client.get("/style")
    assert resp.status_code == 200, resp.text
    assert resp.json() is None


def test_patch_creates_then_updates_singleton(client):
    # First PATCH creates the singleton.
    resp = client.patch("/style", json={"style_prompt": "watercolor", "palette": "earth tones"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    style_id = body["id"]
    assert body["style_prompt"] == "watercolor"
    assert body["palette"] == "earth tones"
    assert body["name"] == "Project style"

    # Second PATCH updates the SAME row, no duplicate.
    resp2 = client.patch("/style", json={"lighting": "golden hour"})
    assert resp2.status_code == 200, resp2.text
    body2 = resp2.json()
    assert body2["id"] == style_id
    assert body2["lighting"] == "golden hour"
    assert body2["style_prompt"] == "watercolor"  # untouched fields preserved

    # GET returns the same single row.
    got = client.get("/style").json()
    assert got["id"] == style_id


def test_patch_reference_assets_drops_unknown_ids(client):
    resp = client.patch(
        "/style", json={"reference_asset_ids": ["asset_bg", "asset_bogus"]}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["reference_asset_ids_json"] == ["asset_bg"]


def test_ingest_passes_scripts_to_derive_style(client, monkeypatch):
    """ingest_style gathers persisted scripts (idea/title/summary) for derive_style."""
    import app.database as _db_mod
    from app.models import Script

    with Session(_db_mod.engine) as s:
        s.add(Script(id="script_1", idea="a cat learns to fly",
                     title="Sky Cat", summary="a cat's flying journey"))
        s.commit()

    captured: dict = {}

    async def fake_derive(**kw):
        captured.update(kw)
        return await FakeLLM().generate(response_model=StyleSpec)

    monkeypatch.setattr("app.services.style_service.derive_style", fake_derive)
    resp = client.post("/style/ingest")
    assert resp.status_code == 200, resp.text
    assert captured["scripts"] == [
        {"idea": "a cat learns to fly", "title": "Sky Cat",
         "summary": "a cat's flying journey"}
    ]


def test_ingest_overwrites_derived_fields_keeps_name(client):
    # Seed a named style with manual fields + a reference asset.
    client.patch(
        "/style",
        json={
            "name": "My kids style",
            "style_prompt": "old prompt",
            "reference_asset_ids": ["asset_bg"],
        },
    )
    resp = client.post("/style/ingest")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["style_prompt"] == "3D cartoon render, soft rounded shapes"
    assert body["palette"] == "soft pastel, warm yellows"
    assert body["lighting"] == "bright morning sunlight"
    assert body["audience"] == "children 2-6"
    assert body["tone"] == "playful, repetitive, gentle"
    # name and reference assets kept.
    assert body["name"] == "My kids style"
    assert body["reference_asset_ids_json"] == ["asset_bg"]

    # GET reflects it, same singleton row.
    got = client.get("/style").json()
    assert got["id"] == body["id"]
    assert got["style_prompt"] == "3D cartoon render, soft rounded shapes"
