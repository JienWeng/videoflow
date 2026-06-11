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
    """QA reviewer stub; `qa` is mutable so tests can simulate failing reviews.
    Captures each QA call's user_prompt so tests can assert on the requirements
    text built by qa_service."""

    def __init__(self):
        from app.schemas import QAResult

        self.qa = QAResult(score=8, passed=True, issues=[], recommendation="accept")
        self.qa_prompts: list[str] = []

    async def generate(self, *, response_model, user_prompt=None, **kw):
        from app.schemas import QAResult

        assert response_model is QAResult
        self.qa_prompts.append(user_prompt or "")
        return self.qa


class FakeAtlas:
    def __init__(self):
        self.videos = 0
        self.payloads: list[dict] = []

    async def upload_media(self, file_path: str) -> str:
        return f"https://static.atlascloud.ai/up/{Path(file_path).name}"

    async def generate_video(self, payload: dict) -> str:
        self.videos += 1
        self.payloads.append(payload)
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
    fake_llm = FakeLLM()
    monkeypatch.setattr("app.agents.base.get_llm_client", lambda: fake_llm)

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
        c.fake_atlas = fake
        c.fake_llm = fake_llm
        yield c


def _wait_for_job(client, job_id: str) -> dict:
    body: dict = {}
    for _ in range(50):
        body = client.get(f"/render-jobs/{job_id}").json()
        if body["job"]["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.1)
    return body


def test_caption_output_endpoint(client, monkeypatch, tmp_path):
    """After a successful render, captions transcribe + style + burn into a new
    file stored on the output row (ASR and FFmpeg mocked).

    Also verifies that whisper timings are kept but text is corrected against
    the known script dialogue when the match is confident.
    """
    from app.services import caption_service

    captured_kwargs: dict = {}

    async def fake_transcribe(video_path, language=None, model_size=None):
        captured_kwargs["model_size"] = model_size
        # Simulate whisper misreading the script dialogue (no space, partial mishear).
        return [caption_service.CaptionSegment(start=0.0, end=2.0, text="我是乐乐乐是我")]

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

    # Seed the render job's stored spec with a quoted dialogue line so the
    # caption service can correct the misheard whisper text.
    from app.database import engine as db_engine
    from app.models.render_job import RenderJob

    with Session(db_engine) as s:
        job = s.get(RenderJob, job_id)
        job.request_json = {
            **job.request_json,
            "prompt": '@Image says 「我是乐乐 乐乐是我」 cheerfully',
            # multi_prompt entries carry durations (as the live payload does), so
            # the duration-windowed alignment path is exercised end-to-end.
            "multi_prompt": [
                {"index": 1, "prompt": '@Image says 「我是乐乐 乐乐是我」 cheerfully', "duration": 3},
                {"index": 2, "prompt": "The kitten just meows", "duration": 2},
            ],
        }
        s.add(job)
        s.commit()

    resp = client.post(f"/outputs/{output_id}/caption", json={"style": "kids", "model": "tiny"})
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["captioned_path"].endswith("_captioned.mp4")
    assert Path(out["captioned_path"]).exists()
    # The ASS subtitle file is kept alongside as an editable artifact.
    ass_path = Path(out["captioned_path"].replace("_captioned.mp4", ".ass"))
    assert ass_path.exists()
    # The ASS file must contain the corrected script text, not the raw whisper mishear.
    ass_text = ass_path.read_text(encoding="utf-8")
    assert "我是乐乐 乐乐是我" in ass_text, "corrected script line should appear in .ass file"
    assert "我是乐乐乐是我" not in ass_text, "raw misheard text should have been corrected"
    # transcribe was called with the requested model size
    assert captured_kwargs.get("model_size") == "tiny"

    # Posting an invalid model name must be rejected with a 4xx.
    resp_bad = client.post(f"/outputs/{output_id}/caption", json={"style": "kids", "model": "bogus"})
    assert resp_bad.status_code in (400, 422), resp_bad.text

    # After captioning, the linked video asset's metadata_json must reflect the
    # captioned_path so the Assets library stays in sync.
    assets = client.get("/assets").json()
    video_assets = [a for a in assets if a["type"] == "video"]
    assert len(video_assets) == 1
    assert video_assets[0]["metadata_json"]["captioned_path"] == out["captioned_path"]


def test_caption_config_endpoint(client):
    r = client.get("/caption-config")
    assert r.status_code == 200
    body = r.json()
    assert "kids" in body["styles"]
    assert "large-v3" in body["models"]
    assert body["default_model"] == "small"
    assert body["default_language"] == "zh"
    # No StyleGuide seeded -> the historical "kids" default.
    assert body["default_style"] == "kids"


def test_caption_config_default_style_follows_style_guide(client):
    from app.database import engine as db_engine
    from app.models import StyleGuide

    with Session(db_engine) as s:
        s.add(StyleGuide(style_prompt="3D cartoon", audience="children aged 3-6"))
        s.commit()
    assert client.get("/caption-config").json()["default_style"] == "kids"

    with Session(db_engine) as s:
        s.add(StyleGuide(style_prompt="cinematic", audience="young adults"))
        s.commit()
    assert client.get("/caption-config").json()["default_style"] == "clean"


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
    # No StyleGuide seeded -> the QA requirements carry no style line.
    assert client.fake_llm.qa_prompts
    assert all("Style guide:" not in p for p in client.fake_llm.qa_prompts)
    # QA must check for the clone bug: duplicated characters in a shot.
    assert all(
        "Each character must appear exactly once per shot" in p
        for p in client.fake_llm.qa_prompts
    )

    # The rendered video must appear in the Assets library.
    assets = client.get("/assets").json()
    video_assets = [a for a in assets if a["type"] == "video"]
    assert len(video_assets) == 1
    a = video_assets[0]
    assert a["file_path"].endswith(".mp4")
    assert a["metadata_json"]["render_job_id"]
    assert a["metadata_json"]["render_output_id"]


def test_qa_prompt_carries_style_line_when_guide_seeded(client):
    """With a project StyleGuide on file, the QA requirements include a style
    line so the vision reviewer judges style adherence too."""
    from app.database import engine as db_engine
    from app.models import StyleGuide

    with Session(db_engine) as s:
        s.add(StyleGuide(style_prompt="3D cartoon", palette="soft pastel", lighting="warm sun"))
        s.commit()

    spec = {
        "scene_id": "scene_x",
        "duration": 5,
        "prompt": "@Image styled pass",
        "reference_images": [{"name": "Image", "asset_id": "asset_ref"}],
    }
    job_id = client.post("/render", json=spec).json()["job_id"]
    body = _wait_for_job(client, job_id)
    assert body["job"]["status"] == "succeeded", body

    assert client.fake_llm.qa_prompts
    assert any(
        "Style guide: 3D cartoon; palette: soft pastel; lighting: warm sun." in p
        for p in client.fake_llm.qa_prompts
    )


def test_qa_prompt_carries_voice_consistency_when_cast_has_voice_rules(client):
    """When any cast bible has voice_rules, the QA requirements carry a
    'Voice consistency:' line so the reviewer (and the human reading the QA
    notes) tracks voice match across renders."""
    from app.database import engine as db_engine
    from app.models import Character, Scene

    with Session(db_engine) as s:
        s.add(Character(id="char_grace", name="Grace",
                        voice_rules_json=["cheerful bright child's voice"]))
        s.add(Scene(id="scene_v", title="t", summary="s", duration=5,
                    character_ids_json=["char_grace"]))
        s.commit()

    spec = {
        "scene_id": "scene_v",
        "duration": 5,
        "prompt": "@Grace waves",
        "reference_images": [{"name": "Image", "asset_id": "asset_ref"}],
    }
    job_id = client.post("/render", json=spec).json()["job_id"]
    body = _wait_for_job(client, job_id)
    assert body["job"]["status"] == "succeeded", body

    assert client.fake_llm.qa_prompts
    assert any(
        "Voice consistency: @Grace — cheerful bright child's voice" in p
        for p in client.fake_llm.qa_prompts
    )


def test_qa_retry_corrective_rerender(client):
    """A failing QA review can be turned into a corrective re-render: the new
    job's prompt carries the QA issues, multi_prompt entries stay as authored,
    and a retry of the retry replaces (never stacks) the corrections suffix."""
    from app.schemas import QAResult

    client.fake_llm.qa = QAResult(
        score=3, passed=False,
        issues=["face distorted", "wrong outfit"],
        recommendation="regenerate",
    )
    spec = {
        "scene_id": "scene_x",
        "duration": 5,
        "prompt": "@Image hero crosses the bridge",
        "reference_images": [{"name": "Image", "asset_id": "asset_ref"}],
        "multi_shot": True,
        "shot_type": "customize",
        "multi_prompt": [
            {"prompt": "shot one 「你好」", "duration": 2},
            {"prompt": "shot two 「再见」", "duration": 3},
        ],
    }
    job_id = client.post("/render", json=spec).json()["job_id"]
    body = _wait_for_job(client, job_id)
    assert body["job"]["status"] == "succeeded", body
    out = body["outputs"][0]
    assert out["qa_json"]["issues"] == ["face distorted", "wrong outfit"]

    # Manual corrective re-render (no automatic retries — renders cost money).
    # The second render's QA finds a NEW issue; set it before its QA runs.
    client.fake_llm.qa = QAResult(
        score=4, passed=False, issues=["lighting too dark"], recommendation="regenerate"
    )
    resp = client.post(f"/outputs/{out['id']}/retry")
    assert resp.status_code == 202, resp.text
    new_job_id = resp.json()["job_id"]
    assert new_job_id != job_id

    body2 = _wait_for_job(client, new_job_id)
    assert body2["job"]["status"] == "succeeded", body2
    assert body2["job"]["scene_id"] == "scene_x"  # lineage: same scene

    payload2 = client.fake_atlas.payloads[1]
    assert "Corrections from review: face distorted; wrong outfit" in payload2["prompt"]
    # Storyboard entries stay exactly as authored.
    assert [p["prompt"] for p in payload2["multi_prompt"]] == [
        "shot one 「你好」", "shot two 「再见」",
    ]

    # Retry of the retry: previous suffix is stripped, only the LATEST issues remain.
    out2 = body2["outputs"][0]
    resp3 = client.post(f"/outputs/{out2['id']}/retry")
    assert resp3.status_code == 202, resp3.text
    payload3 = client.fake_atlas.payloads[2]
    assert payload3["prompt"].count("Corrections from review:") == 1
    assert "lighting too dark" in payload3["prompt"]
    assert "face distorted" not in payload3["prompt"]
    _wait_for_job(client, resp3.json()["job_id"])


def test_qa_retry_without_issues_rejected(client):
    """An output whose QA recorded no issues has nothing to correct -> 4xx."""
    spec = {
        "scene_id": "scene_x",
        "duration": 5,
        "prompt": "@Image clean pass",
        "reference_images": [{"name": "Image", "asset_id": "asset_ref"}],
    }
    job_id = client.post("/render", json=spec).json()["job_id"]
    body = _wait_for_job(client, job_id)
    assert body["job"]["status"] == "succeeded", body
    out_id = body["outputs"][0]["id"]

    resp = client.post(f"/outputs/{out_id}/retry")
    assert resp.status_code == 422, resp.text

    # Unknown output -> 404.
    assert client.post("/outputs/out_nope/retry").status_code == 404
