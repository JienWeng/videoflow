"""Integration tests for Agent Studio endpoints (detail / customization / reset)."""

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


def test_get_agent_detail(client):
    resp = client.get("/settings/agents/scene_agent")
    assert resp.status_code == 200, resp.text
    d = resp.json()
    assert d["agent"] == "scene_agent"
    assert d["default_prompt"]
    assert d["system_prompt"] is None
    assert any(c["key"] == "style" for c in d["context_sources"])
    assert d["customized"] is False


def test_get_agent_detail_unknown_agent_404(client):
    resp = client.get("/settings/agents/nope_agent")
    assert resp.status_code == 404, resp.text


def test_put_customization_sets_prompt_and_tuning(client):
    resp = client.put(
        "/settings/agents/script_agent/customization",
        json={"system_prompt": "Write only haiku.", "temperature": 0.1, "max_retries": 2},
    )
    assert resp.status_code == 200, resp.text
    d = resp.json()
    assert d["system_prompt"] == "Write only haiku."
    assert d["temperature"] == 0.1
    assert d["customized"] is True
    # the live routing cache the structured client reads is updated.
    assert skills.get_effective_skill("script_agent").system_prompt == "Write only haiku."


def test_put_customization_rejects_unknown_placeholder(client):
    resp = client.put(
        "/settings/agents/script_agent/customization",
        json={"system_prompt": "hi {oops}"},
    )
    assert resp.status_code == 422, resp.text


def test_put_customization_context_excludes(client):
    resp = client.put(
        "/settings/agents/scene_agent/customization",
        json={"context_excludes": ["style", "story"]},
    )
    assert resp.status_code == 200, resp.text
    style = next(c for c in resp.json()["context_sources"] if c["key"] == "style")
    assert style["enabled"] is False
    assert skills.context_excludes("scene_agent") == {"style", "story"}


def test_put_customization_rejects_required_context_key(client):
    resp = client.put(
        "/settings/agents/scene_agent/customization",
        json={"context_excludes": ["character_bibles"]},
    )
    assert resp.status_code == 422, resp.text


def test_reset_agent_clears_everything(client):
    client.put(
        "/settings/agents/script_agent/customization",
        json={"system_prompt": "custom", "temperature": 0.1},
    )
    client.put(
        "/settings/agents/script_agent", json={"provider": "minimax", "model": "MiniMax-M2"}
    )
    resp = client.post("/settings/agents/script_agent/reset")
    assert resp.status_code == 200, resp.text
    base = skills.get_skill("script_agent")
    eff = skills.get_effective_skill("script_agent")
    assert eff.system_prompt == base.system_prompt
    assert eff.provider == base.provider
    assert resp.json()["customized"] is False


def test_list_agents_includes_customized_flag(client):
    client.put(
        "/settings/agents/script_agent/customization", json={"system_prompt": "x"}
    )
    resp = client.get("/settings/agents")
    by = {a["agent"]: a for a in resp.json()}
    assert by["script_agent"]["customized"] is True
    assert by["scene_agent"]["customized"] is False
