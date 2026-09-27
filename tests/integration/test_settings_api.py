"""Integration tests for the Settings endpoints."""

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

    # minimax + atlas configured; openai/anthropic/gemini not.
    settings = Settings(
        _env_file=None,
        MINIMAX_API_KEY="mk",
        ATLASCLOUD_API_KEY="ak",
        OPENAI_API_KEY="",
        ANTHROPIC_API_KEY="",
        GEMINI_API_KEY="",
    )
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


def test_list_agents_covers_all_skills(client):
    resp = client.get("/settings/agents")
    assert resp.status_code == 200, resp.text
    agents = {a["agent"] for a in resp.json()}
    assert agents == set(skills.SKILLS)
    one = next(a for a in resp.json() if a["agent"] == "script_agent")
    assert one["label"] == "Script writer"
    assert one["default_provider"] == "opencode-go"
    assert one["provider"] == "opencode-go"
    assert one["default_model"] == "deepseek-v4-flash"


def test_providers_catalog(client):
    resp = client.get("/settings/providers")
    assert resp.status_code == 200, resp.text
    by = {p["name"]: p for p in resp.json()}
    assert by["minimax"]["configured"] is True
    assert by["openai"]["configured"] is False
    assert "MiniMax-M2" in by["minimax"]["models"]


def test_put_override_then_get_reflects_it(client):
    resp = client.put(
        "/settings/agents/script_agent",
        json={"provider": "minimax", "model": "MiniMax-M2"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["model"] == "MiniMax-M2"

    agents = client.get("/settings/agents").json()
    one = next(a for a in agents if a["agent"] == "script_agent")
    assert one["model"] == "MiniMax-M2"
    assert one["default_model"] == "deepseek-v4-flash"


def test_put_unconfigured_provider_is_422(client):
    resp = client.put(
        "/settings/agents/script_agent",
        json={"provider": "openai", "model": "gpt-4o"},
    )
    assert resp.status_code == 422, resp.text


def test_put_free_typed_model_is_accepted(client):
    # Free-typed model ids are accepted for a configured provider (no allowlist).
    resp = client.put(
        "/settings/agents/script_agent",
        json={"provider": "minimax", "model": "nope-but-custom"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["model"] == "nope-but-custom"


def test_override_changes_effective_skill_resolution(client):
    client.put(
        "/settings/agents/scene_agent",
        json={"provider": "atlas", "model": "glm-5v"},
    )
    # The in-process routing cache the structured client reads is updated.
    eff = skills.get_effective_skill("scene_agent")
    assert eff.provider == "atlas"
    assert eff.model == "glm-5v"


def test_clear_override_reverts(client):
    client.put(
        "/settings/agents/scene_agent",
        json={"provider": "minimax", "model": "MiniMax-M2"},
    )
    resp = client.put(
        "/settings/agents/scene_agent", json={"provider": None, "model": None}
    )
    assert resp.status_code == 200, resp.text
    base = skills.get_skill("scene_agent")
    assert skills.get_effective_skill("scene_agent").provider == base.provider
