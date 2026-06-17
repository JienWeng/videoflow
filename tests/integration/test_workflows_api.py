"""Integration tests for the autopilot /workflows endpoints (no live loop)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.config import Settings
from app.database import get_session
from app.services import autopilot_service


@pytest.fixture
def client(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr("app.services.poll_service.engine", engine)
    monkeypatch.setattr("app.jobs.worker.reconcile_pending", lambda: 0)
    # Don't kick off the real director loop in tests — just create the run row.
    monkeypatch.setattr(
        autopilot_service, "start_run",
        lambda session, **kw: autopilot_service.create_run(session, **kw),
    )

    settings = Settings(_env_file=None, MINIMAX_API_KEY="mk", ATLASCLOUD_API_KEY="ak")
    monkeypatch.setattr("app.services.settings_service.get_settings", lambda: settings)

    from app.main import create_app

    app = create_app()

    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as c:
        yield c


def test_create_and_get_workflow(client):
    resp = client.post("/workflows", json={"idea": "a cat learns to fly", "config": {"budget": 300}})
    assert resp.status_code == 200, resp.text
    run = resp.json()
    assert run["status"] == "running"
    assert run["idea"] == "a cat learns to fly"

    rid = run["id"]
    detail = client.get(f"/workflows/{rid}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["run"]["id"] == rid
    assert body["steps"] == []
    assert body["output"] is None


def test_list_and_cancel_workflow(client):
    rid = client.post("/workflows", json={"idea": "x"}).json()["id"]
    listed = client.get("/workflows").json()
    assert any(r["id"] == rid for r in listed)

    cancelled = client.post(f"/workflows/{rid}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"


def test_get_unknown_workflow_404(client):
    assert client.get("/workflows/nope").status_code == 404
