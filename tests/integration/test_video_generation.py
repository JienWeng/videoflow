"""User-facing Create video endpoint tests."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import create_app


def test_generate_video_starts_background_operation(monkeypatch):
    captured: dict = {}

    def fake_start_op(kind, coro_factory, *, summarize, project_id):
        captured["kind"] = kind
        captured["summarize"] = summarize
        captured["project_id"] = project_id
        return SimpleNamespace(id="op_video_1", status="running")

    monkeypatch.setattr("app.api.videos.op_service.start_op", fake_start_op)

    with TestClient(create_app()) as client:
        response = client.post(
            "/videos/generate?background=true",
            json={"idea": "A child learns why the moon is round."},
        )

    assert response.status_code == 202
    assert response.json() == {"op_id": "op_video_1", "status": "running"}
    assert captured["kind"] == "video_generation"


def test_generate_video_rejects_empty_idea():
    with TestClient(create_app()) as client:
        response = client.post("/videos/generate", json={"idea": ""})

    assert response.status_code == 422
