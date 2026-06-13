"""API surface for the product-grade library: character PATCH, asset taxonomy
endpoint, and multi-file upload. No LLM/network — only the persistence paths."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import create_app
from app.schemas.common import ASSET_TYPES


@pytest.fixture
def client(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    import app.models  # noqa: F401

    SQLModel.metadata.create_all(engine)

    monkeypatch.setattr("app.config.Settings.ensure_dirs", lambda self: None)
    monkeypatch.setattr(
        "app.services.asset_service.get_settings",
        lambda: type(
            "S", (), {"assets_dir": tmp_path, "ensure_dirs": lambda s=None: None}
        )(),
    )

    app = create_app()

    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session
    return TestClient(app)


def test_asset_types_endpoint_returns_canonical_vocabulary(client):
    out = client.get("/assets/types").json()
    assert out["types"] == list(ASSET_TYPES)


def test_patch_character_updates_fields(client):
    cid = client.post("/characters", json={"name": "Lele"}).json()["id"]
    out = client.patch(
        f"/characters/{cid}",
        json={
            "appearance": "red hoodie",
            "personality": "curious",
            "visual_rules": ["red hoodie always"],
        },
    ).json()
    assert out["appearance"] == "red hoodie"
    assert out["personality"] == "curious"
    assert out["visual_rules_json"] == ["red hoodie always"]
    assert out["name"] == "Lele"


def test_patch_character_blank_name_is_422(client):
    cid = client.post("/characters", json={"name": "Lele"}).json()["id"]
    resp = client.patch(f"/characters/{cid}", json={"name": "  "})
    assert resp.status_code == 422


def test_single_file_upload_returns_one_asset(client):
    files = {"file": ("a.png", io.BytesIO(b"x"), "image/png")}
    out = client.post("/assets/upload", files=files, data={"asset_type": "prop"}).json()
    assert isinstance(out, dict)
    assert out["type"] == "prop"


def test_multi_file_upload_returns_list(client):
    files = [
        ("file", ("a.png", io.BytesIO(b"x"), "image/png")),
        ("file", ("b.png", io.BytesIO(b"y"), "image/png")),
    ]
    out = client.post("/assets/upload", files=files, data={"asset_type": "background"}).json()
    assert isinstance(out, list)
    assert len(out) == 2
    assert {a["type"] for a in out} == {"background"}
    assert len({a["id"] for a in out}) == 2
