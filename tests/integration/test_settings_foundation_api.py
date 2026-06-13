"""Integration tests for the settings-foundation endpoints:
providers (keys/base-urls), app defaults resolver."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.config import Settings
from app.database import get_session
from app.llm import skills


@pytest.fixture
def client(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr("app.services.poll_service.engine", engine)
    monkeypatch.setattr("app.jobs.worker.reconcile_pending", lambda: 0)

    settings = Settings(
        _env_file=None,
        MINIMAX_API_KEY="mk",
        ATLASCLOUD_API_KEY="ak",
        OPENAI_API_KEY="",
        ANTHROPIC_API_KEY="",
        GEMINI_API_KEY="",
        DEFAULT_ASPECT_RATIO="9:16",
    )
    # Pin get_settings everywhere the service/config read it.
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.settings_service.get_settings", lambda: settings)
    skills.clear_overrides()

    from app.main import create_app

    app = create_app()

    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as c:
        yield c
    skills.clear_overrides()


# ----------------------------------------------------------------- providers
def test_providers_catalog_reports_allow_custom(client):
    resp = client.get("/settings/providers")
    assert resp.status_code == 200, resp.text
    by = {p["name"]: p for p in resp.json()}
    assert by["minimax"]["allow_custom"] is True
    assert "suggested_models" in by["minimax"]


def test_get_provider_masks_key(client):
    client.put("/settings/providers/openai", json={"api_key": "sk-secret-abcd1234"})
    resp = client.get("/settings/providers/openai")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["configured"] is True
    assert body["masked_key"].endswith("1234")
    assert "secret" not in body["masked_key"]
    assert "api_key" not in body  # raw key never returned


def test_put_provider_then_catalog_shows_configured(client):
    # openai not in env -> not configured initially.
    by = {p["name"]: p for p in client.get("/settings/providers").json()}
    assert by["openai"]["configured"] is False

    resp = client.put("/settings/providers/openai", json={"api_key": "sk-fromdb-9999"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["configured"] is True

    by = {p["name"]: p for p in client.get("/settings/providers").json()}
    assert by["openai"]["configured"] is True
    assert by["openai"]["from_db"] is True


def test_put_provider_base_url_only(client):
    client.put("/settings/providers/openai", json={"api_key": "sk-x"})
    resp = client.put(
        "/settings/providers/openai", json={"base_url": "https://proxy.example/v1"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["base_url"] == "https://proxy.example/v1"
    assert resp.json()["configured"] is True  # key preserved


def test_put_unknown_provider_404(client):
    resp = client.put("/settings/providers/bogus", json={"api_key": "x"})
    assert resp.status_code == 404, resp.text


def test_db_key_enables_agent_override_for_unconfigured_env_provider(client):
    # openai unconfigured in env; persist a DB key, then override an agent to it.
    client.put("/settings/providers/openai", json={"api_key": "sk-db"})
    resp = client.put(
        "/settings/agents/script_agent",
        json={"provider": "openai", "model": "gpt-4o"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["provider"] == "openai"


# ----------------------------------------------------------------- app defaults
def test_get_app_settings_returns_resolved_defaults(client):
    resp = client.get("/settings/app")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["default_aspect_ratio"] == "9:16"  # config default
    # Every documented key present.
    for k in (
        "default_scene_duration",
        "caption_style",
        "caption_language",
        "whisper_model",
        "dialogue_language",
        "image_model",
        "ref_image_model",
        "video_model",
        "vl_model",
        "max_video_refs",
        "render_negatives",
    ):
        assert k in body


def test_put_app_settings_overrides_and_persists(client):
    resp = client.put(
        "/settings/app",
        json={"default_aspect_ratio": "16:9", "render_negatives": ["blurry"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["default_aspect_ratio"] == "16:9"
    assert resp.json()["render_negatives"] == ["blurry"]

    # Persisted across a fresh GET.
    again = client.get("/settings/app").json()
    assert again["default_aspect_ratio"] == "16:9"
    assert again["render_negatives"] == ["blurry"]


def test_put_app_settings_ignores_unknown_keys(client):
    # Unknown keys are simply not in the request schema; known partial works.
    resp = client.put("/settings/app", json={"max_video_refs": 5})
    assert resp.status_code == 200, resp.text
    assert resp.json()["max_video_refs"] == 5
