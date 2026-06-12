"""Integration: /projects endpoints + transparent active-project scoping.

The pre-existing rows are seeded with project_id NULL (exactly like a
pre-projects database); the first scoped request must adopt them into the
lazily-created default project, and switching projects must hide them.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.database import get_session
from app.models import Asset, Character, Scene, StyleGuide


@pytest.fixture
def client(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr("app.services.poll_service.engine", engine)
    monkeypatch.setattr("app.jobs.worker.reconcile_pending", lambda: 0)

    # Pre-projects data: everything seeded with project_id NULL.
    with Session(engine) as s:
        s.add(Character(id="char_grace", name="Grace"))
        s.add(Asset(id="asset_cup", name="Cup", type="prop"))
        s.add(Scene(id="scene_1", title="Meadow", summary="a meadow lesson"))
        s.add(StyleGuide(id="style_1", style_prompt="watercolor"))
        s.commit()

    from app.main import create_app

    app = create_app()

    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as c:
        yield c


def test_default_project_adopts_existing_data(client):
    resp = client.get("/projects/active")
    assert resp.status_code == 200, resp.text
    active = resp.json()
    assert active["name"] == "My project"
    assert active["is_active"] is True
    assert active["counts"] == {
        "scenes": 1, "characters": 1, "assets": 1, "scripts": 0,
    }

    # Existing endpoints keep working, now scoped to the default project.
    assert [s["id"] for s in client.get("/scenes").json()] == ["scene_1"]
    assert [c["id"] for c in client.get("/characters").json()] == ["char_grace"]
    assert [a["id"] for a in client.get("/assets").json()] == ["asset_cup"]
    assert client.get("/style").json()["id"] == "style_1"

    projects = client.get("/projects").json()
    assert len(projects) == 1 and projects[0]["id"] == active["id"]


def test_switching_projects_scopes_everything(client):
    default_id = client.get("/projects/active").json()["id"]

    # POST /projects creates AND activates.
    resp = client.post("/projects", json={"name": "Project B", "description": "b"})
    assert resp.status_code == 200, resp.text
    b = resp.json()
    assert b["is_active"] is True
    assert client.get("/projects/active").json()["id"] == b["id"]

    # B is empty: lists, graph and style see nothing of the default project.
    assert client.get("/scenes").json() == []
    assert client.get("/characters").json() == []
    assert client.get("/assets").json() == []
    assert client.get("/scripts").json() == []
    assert client.get("/render-jobs").json() == []
    assert client.get("/style").json() is None
    graph = client.get("/graph").json()
    assert graph["nodes"] == [] and graph["edges"] == []

    # Create data inside B — visible in B.
    char = client.post("/characters", json={"name": "Bob"}).json()
    assert [c["id"] for c in client.get("/characters").json()] == [char["id"]]
    style_b = client.patch("/style", json={"style_prompt": "neon"}).json()
    assert style_b["id"] != "style_1"
    assert client.get("/style").json()["style_prompt"] == "neon"

    # Switch back to the default project: its data intact, B's hidden.
    resp = client.post(f"/projects/{default_id}/activate")
    assert resp.status_code == 200, resp.text
    assert [s["id"] for s in client.get("/scenes").json()] == ["scene_1"]
    assert [c["id"] for c in client.get("/characters").json()] == ["char_grace"]
    assert client.get("/style").json()["style_prompt"] == "watercolor"
    node_ids = {n["id"] for n in client.get("/graph").json()["nodes"]}
    assert node_ids == {"scene_1", "char_grace", "asset_cup"}
    assert char["id"] not in node_ids

    # Counts per project.
    by_id = {p["id"]: p for p in client.get("/projects").json()}
    assert by_id[default_id]["counts"]["characters"] == 1
    assert by_id[b["id"]]["counts"]["characters"] == 1
    assert by_id[b["id"]]["counts"]["scenes"] == 0


def test_patch_and_delete_project(client):
    default_id = client.get("/projects/active").json()["id"]
    b = client.post("/projects", json={"name": "B"}).json()

    # PATCH (rename) while active.
    resp = client.patch(f"/projects/{b['id']}", json={"name": "B2"})
    assert resp.status_code == 200 and resp.json()["name"] == "B2"

    # Deleting the ACTIVE project is rejected.
    resp = client.delete(f"/projects/{b['id']}")
    assert resp.status_code == 422

    # Put data in B, switch away, delete B: its rows go, default's stay.
    client.post("/characters", json={"name": "Bob"})
    client.post(f"/projects/{default_id}/activate")
    resp = client.delete(f"/projects/{b['id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["rows"]["characters"] == 1

    projects = client.get("/projects").json()
    assert [p["id"] for p in projects] == [default_id]
    assert [c["id"] for c in client.get("/characters").json()] == ["char_grace"]

    # Unknown project ids 404.
    assert client.post("/projects/project_nope/activate").status_code == 404
    assert client.delete("/projects/project_nope").status_code == 404


def test_chat_options_scoped_to_active_project(client, monkeypatch):
    from app.schemas import Intent

    class FakeLLM:
        async def generate(self, **kw):
            return Intent(reply="ok")

    monkeypatch.setattr("app.agents.base.get_llm_client", lambda: FakeLLM())

    body = client.post("/chat", json={"message": "hi"}).json()
    assert [s["id"] for s in body["options"]["scenes"]] == ["scene_1"]
    assert [c["id"] for c in body["options"]["characters"]] == ["char_grace"]

    client.post("/projects", json={"name": "B"})
    body = client.post("/chat", json={"message": "hi"}).json()
    assert body["options"]["scenes"] == []
    assert body["options"]["characters"] == []
