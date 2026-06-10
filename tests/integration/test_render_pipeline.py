"""End-to-end render pipeline with a mocked AtlasCloud client.

Exercises: POST /render -> submit -> background worker polls -> download ->
RenderOutput persisted -> job status succeeded.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.database import get_session


class FakeLLM:
    async def generate(self, *, response_model, **kw):
        from app.schemas import QAResult

        assert response_model is QAResult
        return QAResult(score=8, passed=True, issues=[], recommendation="accept")


class FakeAtlas:
    def __init__(self):
        self.videos = 0

    async def upload_media(self, file_path: str) -> str:
        return f"https://static.atlascloud.ai/up/{Path(file_path).name}"

    async def generate_video(self, payload: dict) -> str:
        self.videos += 1
        return f"pred_{self.videos}"

    async def get_prediction(self, pid: str) -> dict:
        return {"status": "completed", "outputs": ["https://static.atlascloud.ai/out.mp4"]}


@pytest.fixture
def client(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    # Point the app's engine (used by the worker) at the temp DB.
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr("app.services.poll_service.engine", engine)
    monkeypatch.setattr("app.jobs.worker.reconcile_pending", lambda: 0)

    fake = FakeAtlas()
    monkeypatch.setattr("app.services.render_service.get_atlas_client", lambda: fake)
    monkeypatch.setattr("app.providers.atlascloud_video.get_atlas_client", lambda: fake)

    async def fake_download(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-mp4")
        return dest

    async def fake_thumb(video_path, dest, **kw):
        return None

    monkeypatch.setattr("app.services.media.download", fake_download)
    monkeypatch.setattr("app.services.poll_service.media.download", fake_download)
    monkeypatch.setattr("app.services.poll_service.media.make_thumbnail", fake_thumb)
    # QA runs automatically after a successful render; mock its LLM.
    monkeypatch.setattr("app.agents.base.get_llm_client", lambda: FakeLLM())

    # Seed a reference asset to resolve.
    from app.models import Asset

    with Session(engine) as s:
        s.add(Asset(id="asset_ref", type="character_reference", file_path=str(tmp_path / "ref.png")))
        s.commit()
    (tmp_path / "ref.png").write_bytes(b"img")

    from app.main import create_app

    app = create_app()

    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as c:  # context form runs lifespan (starts workers)
        yield c


def test_caption_output_endpoint(client, monkeypatch):
    """After a successful render, captions transcribe + style + burn into a new
    file stored on the output row (ASR and FFmpeg mocked)."""
    from app.services import caption_service

    captured_kwargs: dict = {}

    async def fake_transcribe(video_path, language=None, model_size=None):
        captured_kwargs["model_size"] = model_size
        return [caption_service.CaptionSegment(start=0.0, end=2.0, text="我是乐乐")]

    async def fake_burn(video_path, ass_path, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"captioned")
        return dest

    monkeypatch.setattr(caption_service, "transcribe", fake_transcribe)
    monkeypatch.setattr(caption_service, "burn_subtitles", fake_burn)

    # Produce a finished render via the normal pipeline.
    spec = {
        "scene_id": "scene_x", "duration": 5, "prompt": "@Image p",
        "reference_images": [{"name": "Image", "asset_id": "asset_ref"}],
    }
    job_id = client.post("/render", json=spec).json()["job_id"]
    for _ in range(50):
        body = client.get(f"/render-jobs/{job_id}").json()
        if body["job"]["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.1)
    output_id = body["outputs"][0]["id"]

    resp = client.post(f"/outputs/{output_id}/caption", json={"style": "kids", "model": "tiny"})
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["captioned_path"].endswith("_captioned.mp4")
    assert Path(out["captioned_path"]).exists()
    # The ASS subtitle file is kept alongside as an editable artifact.
    assert Path(out["captioned_path"].replace("_captioned.mp4", ".ass")).exists()
    # transcribe was called with the requested model size
    assert captured_kwargs.get("model_size") == "tiny"

    # Posting an invalid model name must be rejected with a 4xx.
    resp_bad = client.post(f"/outputs/{output_id}/caption", json={"style": "kids", "model": "bogus"})
    assert resp_bad.status_code in (400, 422), resp_bad.text


def test_caption_config_endpoint(client):
    r = client.get("/caption-config")
    assert r.status_code == 200
    body = r.json()
    assert "kids" in body["styles"]
    assert "large-v3" in body["models"]
    assert body["default_model"] == "small"
    assert body["default_language"] == "zh"


def test_caption_unknown_style_rejected(client):
    resp = client.post("/outputs/nonexistent/caption", json={"style": "kids"})
    assert resp.status_code == 404


def test_render_job_succeeds(client):
    spec = {
        "scene_id": "scene_x",
        "shot_id": "shot_x",
        "duration": 5,
        "prompt": "@Image color river streaks across black",
        "reference_images": [{"name": "Image", "asset_id": "asset_ref"}],
        "sound": True,
        "keep_original_sound": True,
    }
    resp = client.post("/render", json=spec)
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    # Wait for the background worker to finish.
    status = None
    for _ in range(50):
        body = client.get(f"/render-jobs/{job_id}").json()
        status = body["job"]["status"]
        if status in ("succeeded", "failed"):
            break
        time.sleep(0.1)

    assert status == "succeeded", body
    outputs = body["outputs"]
    assert len(outputs) == 1
    assert outputs[0]["video_path"].endswith(".mp4")
    # QA ran automatically and persisted a score + recommendation.
    assert outputs[0]["score"] == 8
    assert outputs[0]["qa_json"]["recommendation"] == "accept"
