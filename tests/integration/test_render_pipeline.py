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

    # The post-correction segments are persisted on the output row so the
    # caption editor can load them without re-running whisper.
    assert out["captions_json"]["style"] == "kids"
    assert out["captions_json"]["segments"] == [
        {"start": 0.0, "end": 2.0, "text": "我是乐乐 乐乐是我"}
    ]

    # Posting an invalid model name must be rejected with a 4xx.
    resp_bad = client.post(f"/outputs/{output_id}/caption", json={"style": "kids", "model": "bogus"})
    assert resp_bad.status_code in (400, 422), resp_bad.text

    # After captioning, the linked video asset's metadata_json must reflect the
    # captioned_path so the Assets library stays in sync.
    assets = client.get("/assets").json()
    video_assets = [a for a in assets if a["type"] == "video"]
    assert len(video_assets) == 1
    assert video_assets[0]["metadata_json"]["captioned_path"] == out["captioned_path"]


def test_caption_editor_roundtrip(client, monkeypatch):
    """GET /outputs/{id}/captions exposes the stored segments; PUT validates the
    edits, rebuilds the .ass and re-burns (burn mocked, build_ass real) without
    re-running whisper."""
    from app.services import caption_service

    transcribe_calls = {"n": 0}

    async def fake_transcribe(video_path, language=None, model_size=None):
        transcribe_calls["n"] += 1
        return [
            caption_service.CaptionSegment(start=0.0, end=2.0, text="第一句"),
            caption_service.CaptionSegment(start=2.5, end=4.0, text="第二句"),
        ]

    async def fake_burn(video_path, ass_path, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"captioned")
        return dest

    monkeypatch.setattr(caption_service, "transcribe", fake_transcribe)
    monkeypatch.setattr(caption_service, "burn_subtitles", fake_burn)

    # Unknown output -> 404 on both verbs.
    assert client.get("/outputs/nonexistent/captions").status_code == 404
    assert (
        client.put(
            "/outputs/nonexistent/captions",
            json={"segments": [{"start": 0, "end": 1, "text": "x"}]},
        ).status_code
        == 404
    )

    # Produce a finished render.
    spec = {
        "scene_id": "scene_x", "duration": 5, "prompt": "@Image p",
        "reference_images": [{"name": "Image", "asset_id": "asset_ref"}],
    }
    job_id = client.post("/render", json=spec).json()["job_id"]
    body = _wait_for_job(client, job_id)
    output_id = body["outputs"][0]["id"]

    # Never captioned -> available=False with empty segments.
    r = client.get(f"/outputs/{output_id}/captions")
    assert r.status_code == 200
    assert r.json() == {"segments": [], "style": None, "available": False}

    # Auto-caption, then edit.
    assert client.post(
        f"/outputs/{output_id}/caption", json={"style": "clean", "model": "tiny"}
    ).status_code == 200
    assert transcribe_calls["n"] == 1

    r = client.get(f"/outputs/{output_id}/captions").json()
    assert r["available"] is True
    assert r["style"] == "clean"
    assert [s["text"] for s in r["segments"]] == ["第一句", "第二句"]

    # Edit text + timing (deliberately unsorted; empty line dropped silently).
    edited = [
        {"start": 2.5, "end": 4.2, "text": "改好的第二句"},
        {"start": 0.0, "end": 2.0, "text": " 改好的第一句 "},
        {"start": 5.0, "end": 6.0, "text": "   "},
    ]
    r = client.put(f"/outputs/{output_id}/captions", json={"segments": edited})
    assert r.status_code == 200, r.text
    out = r.json()
    assert transcribe_calls["n"] == 1, "re-burn must not re-run whisper"
    assert out["captions_json"]["segments"] == [
        {"start": 0.0, "end": 2.0, "text": "改好的第一句"},
        {"start": 2.5, "end": 4.2, "text": "改好的第二句"},
    ]
    # Style defaults to the stored one when the body omits it.
    assert out["captions_json"]["style"] == "clean"
    assert out["captioned_path"].endswith("_captioned.mp4")
    ass_text = Path(out["captioned_path"].replace("_captioned.mp4", ".ass")).read_text(
        encoding="utf-8"
    )
    assert "改好的第一句" in ass_text and "改好的第二句" in ass_text
    assert "第一句\n" not in ass_text.replace("改好的第一句", "")

    # GET reflects the edits.
    r = client.get(f"/outputs/{output_id}/captions").json()
    assert [s["text"] for s in r["segments"]] == ["改好的第一句", "改好的第二句"]

    # A style override is applied and persisted.
    r = client.put(
        f"/outputs/{output_id}/captions",
        json={"segments": [{"start": 0, "end": 1, "text": "x"}], "style": "kids"},
    )
    assert r.status_code == 200
    assert r.json()["captions_json"]["style"] == "kids"

    # Invalid timing -> 422; unknown style -> 422; no usable segments -> 422.
    bad = client.put(
        f"/outputs/{output_id}/captions",
        json={"segments": [{"start": 2.0, "end": 2.0, "text": "x"}]},
    )
    assert bad.status_code == 422
    assert client.put(
        f"/outputs/{output_id}/captions",
        json={"segments": [{"start": 0, "end": 1, "text": "x"}], "style": "bogus"},
    ).status_code == 422
    assert client.put(
        f"/outputs/{output_id}/captions", json={"segments": [{"start": 0, "end": 1, "text": " "}]}
    ).status_code == 422


def test_caption_config_endpoint(client):
    r = client.get("/caption-config")
    assert r.status_code == 200
    body = r.json()
    assert "kids" in body["styles"]
    assert "large-v3" in body["models"]
    assert body["default_model"] == "small"
    # default_language now comes from the settings resolver (config default
    # 'auto' = let whisper auto-detect), not the old hardcoded "zh".
    assert body["default_language"] == "auto"
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


# ---------------------------------------------------------------------------
# Editor endpoint tests
# ---------------------------------------------------------------------------

def test_editor_endpoint_404_for_unknown_output(client):
    """GET /outputs/unknown/editor returns 404."""
    resp = client.get("/outputs/out_nonexistent/editor")
    assert resp.status_code == 404


def test_editor_endpoint_multi_prompt_shots_with_shot_ids(client, monkeypatch):
    """Editor endpoint returns shot blocks with cumulative times from multi_prompt,
    shot_ids attached from the scene's Shot rows by order, captions section,
    qa_issues, and scene title."""
    from app.services import caption_service

    async def fake_transcribe(video_path, language=None, model_size=None):
        return [caption_service.CaptionSegment(start=0.0, end=2.0, text="hello")]

    async def fake_burn(video_path, ass_path, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"captioned")
        return dest

    monkeypatch.setattr(caption_service, "transcribe", fake_transcribe)
    monkeypatch.setattr(caption_service, "burn_subtitles", fake_burn)

    from app.database import engine as db_engine
    from app.models import Scene, Shot
    from app.models.render_job import RenderJob

    # Create a scene with Shot rows in order.
    with Session(db_engine) as s:
        scene = Scene(id="scene_editor", title="Editor Scene", summary="s", duration=8)
        s.add(scene)
        shot1 = Shot(id="shot_e1", scene_id="scene_editor", shot_order=0, duration=3,
                     prompt="shot one prompt", camera="wide", movement="pan left")
        shot2 = Shot(id="shot_e2", scene_id="scene_editor", shot_order=1, duration=5,
                     prompt="shot two prompt", camera="close", movement=None)
        s.add(shot1)
        s.add(shot2)
        s.commit()

    # Submit a multi-prompt render for that scene.
    spec = {
        "scene_id": "scene_editor",
        "duration": 8,
        "prompt": "@Image main prompt",
        "reference_images": [{"name": "Image", "asset_id": "asset_ref"}],
        "multi_shot": True,
        "shot_type": "customize",
        "multi_prompt": [
            {"prompt": "shot one prompt", "duration": 3},
            {"prompt": "shot two prompt", "duration": 5},
        ],
    }
    job_id = client.post("/render", json=spec).json()["job_id"]
    body = _wait_for_job(client, job_id)
    assert body["job"]["status"] == "succeeded", body
    output_id = body["outputs"][0]["id"]

    # Add captions so the captions section shows available=True.
    assert client.post(
        f"/outputs/{output_id}/caption", json={"style": "kids", "model": "tiny"}
    ).status_code == 200

    resp = client.get(f"/outputs/{output_id}/editor")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # output block
    assert data["output"]["id"] == output_id
    assert data["output"]["video_path"] is not None
    assert "qa_issues" in data["output"]

    # captions block — same shape as GET /captions
    caps = data["captions"]
    assert caps["available"] is True
    assert caps["style"] == "kids"
    assert len(caps["segments"]) == 1

    # scene block
    assert data["scene"]["id"] == "scene_editor"
    assert data["scene"]["title"] == "Editor Scene"

    # shots block — 2 entries with cumulative start/end
    shots = data["shots"]
    assert len(shots) == 2

    assert shots[0]["index"] == 1
    assert shots[0]["start"] == 0.0
    assert shots[0]["end"] == 3.0
    assert shots[0]["duration"] == 3
    assert shots[0]["prompt"] == "shot one prompt"
    assert shots[0]["shot_id"] == "shot_e1"
    assert shots[0]["camera"] == "wide"
    assert shots[0]["movement"] == "pan left"

    assert shots[1]["index"] == 2
    assert shots[1]["start"] == 3.0
    assert shots[1]["end"] == 8.0
    assert shots[1]["duration"] == 5
    assert shots[1]["prompt"] == "shot two prompt"
    assert shots[1]["shot_id"] == "shot_e2"
    assert shots[1]["camera"] == "close"
    assert shots[1]["movement"] is None

    assert data["total_duration"] == 8.0


def test_editor_endpoint_single_prompt_render(client):
    """Single-prompt render (no multi_prompt) -> one shot block spanning spec duration."""
    spec = {
        "scene_id": "scene_x",
        "duration": 5,
        "prompt": "@Image solo prompt",
        "reference_images": [{"name": "Image", "asset_id": "asset_ref"}],
    }
    job_id = client.post("/render", json=spec).json()["job_id"]
    body = _wait_for_job(client, job_id)
    assert body["job"]["status"] == "succeeded", body
    output_id = body["outputs"][0]["id"]

    resp = client.get(f"/outputs/{output_id}/editor")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    shots = data["shots"]
    assert len(shots) == 1
    assert shots[0]["index"] == 1
    assert shots[0]["start"] == 0.0
    assert shots[0]["end"] == 5.0
    assert shots[0]["duration"] == 5
    assert shots[0]["prompt"] == "@Image solo prompt"
    assert shots[0]["shot_id"] is None
    assert data["total_duration"] == 5.0

    # captions not yet generated -> available=False
    assert data["captions"]["available"] is False


def test_editor_endpoint_legacy_job_no_spec(client):
    """A job with no spec stored -> shots: [], total_duration: 0."""
    from app.database import engine as db_engine
    from app.models.render_job import RenderJob, RenderStatus
    from app.models.render_output import RenderOutput

    with Session(db_engine) as s:
        job = RenderJob(
            id="job_legacy",
            scene_id=None,
            status=RenderStatus.succeeded,
            request_json={},  # no spec key
        )
        s.add(job)
        output = RenderOutput(
            id="out_legacy",
            render_job_id="job_legacy",
            video_path="/tmp/legacy.mp4",
        )
        s.add(output)
        s.commit()

    resp = client.get("/outputs/out_legacy/editor")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["shots"] == []
    assert data["total_duration"] == 0
    assert data["scene"] is None


def test_editor_endpoint_shot_count_mismatch(client):
    """When shot rows count != multi_prompt count, unmatched blocks get shot_id: null."""
    from app.database import engine as db_engine
    from app.models import Scene, Shot
    from app.models.render_job import RenderJob, RenderStatus
    from app.models.render_output import RenderOutput

    # Scene with only 1 shot row (shots regenerated since render).
    with Session(db_engine) as s:
        scene = Scene(id="scene_mismatch", title="Mismatch Scene", summary="s", duration=8)
        s.add(scene)
        shot1 = Shot(id="shot_m1", scene_id="scene_mismatch", shot_order=0, duration=3,
                     prompt="first", camera="wide", movement=None)
        s.add(shot1)
        s.commit()

    # A job with 2 multi_prompt entries but only 1 shot row.
    with Session(db_engine) as s:
        job = RenderJob(
            id="job_mismatch",
            scene_id="scene_mismatch",
            status=RenderStatus.succeeded,
            request_json={
                "spec": {
                    "prompt": "main",
                    "duration": 8,
                    "multi_prompt": [
                        {"index": 1, "prompt": "block one", "duration": 3},
                        {"index": 2, "prompt": "block two", "duration": 5},
                    ],
                }
            },
        )
        s.add(job)
        output = RenderOutput(
            id="out_mismatch",
            render_job_id="job_mismatch",
            video_path="/tmp/mismatch.mp4",
        )
        s.add(output)
        s.commit()

    resp = client.get("/outputs/out_mismatch/editor")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    shots = data["shots"]
    assert len(shots) == 2
    # First block matched to shot_m1.
    assert shots[0]["shot_id"] == "shot_m1"
    # Second block unmatched -> null.
    assert shots[1]["shot_id"] is None


# ---------------------------------------------------------------------------
# "Finished video out": download, select, run-qa, resubmit, stage tracking
# ---------------------------------------------------------------------------

def _finished_output(client, scene_id="scene_x", title=None):
    """Render once and return (job_id, body, output_id). Optionally name the scene
    so the download filename test can assert the slug."""
    if title is not None:
        from app.database import engine as db_engine
        from app.models import Scene

        with Session(db_engine) as s:
            s.add(Scene(id=scene_id, title=title, summary="s", duration=5))
            s.commit()
    spec = {
        "scene_id": scene_id,
        "duration": 5,
        "prompt": "@Image p",
        "reference_images": [{"name": "Image", "asset_id": "asset_ref"}],
    }
    job_id = client.post("/render", json=spec).json()["job_id"]
    body = _wait_for_job(client, job_id)
    assert body["job"]["status"] == "succeeded", body
    return job_id, body, body["outputs"][0]["id"]


def test_download_raw_returns_attachment_with_slug_filename(client):
    _, _, output_id = _finished_output(client, scene_id="scene_dl", title="乐乐 Big Day")
    resp = client.get(f"/outputs/{output_id}/download")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "video/mp4"
    cd = resp.headers["content-disposition"]
    assert "attachment" in cd
    assert ".mp4" in cd
    assert output_id in cd
    assert "Big-Day" in cd
    assert resp.content == b"fake-mp4"


def test_download_unknown_output_404(client):
    assert client.get("/outputs/out_nope/download").status_code == 404


def test_download_captioned_missing_404(client):
    _, _, output_id = _finished_output(client)
    # Never captioned -> the captioned variant 404s.
    assert client.get(f"/outputs/{output_id}/download?variant=captioned").status_code == 404


def test_download_captioned_after_caption(client, monkeypatch):
    from app.services import caption_service

    async def fake_transcribe(video_path, language=None, model_size=None):
        return [caption_service.CaptionSegment(start=0.0, end=2.0, text="hi")]

    async def fake_burn(video_path, ass_path, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"captioned-mp4")
        return dest

    monkeypatch.setattr(caption_service, "transcribe", fake_transcribe)
    monkeypatch.setattr(caption_service, "burn_subtitles", fake_burn)

    _, _, output_id = _finished_output(client)
    assert client.post(
        f"/outputs/{output_id}/caption", json={"style": "kids", "model": "tiny"}
    ).status_code == 200

    resp = client.get(f"/outputs/{output_id}/download?variant=captioned")
    assert resp.status_code == 200, resp.text
    assert "captioned" in resp.headers["content-disposition"]
    assert resp.content == b"captioned-mp4"


def test_select_output_marks_selected(client):
    _, _, output_id = _finished_output(client)
    r = client.patch(f"/outputs/{output_id}/select")
    assert r.status_code == 200, r.text
    assert r.json()["selected"] is True

    # Clearing works too.
    r = client.patch(f"/outputs/{output_id}/select", json={"selected": False})
    assert r.status_code == 200
    assert r.json()["selected"] is False

    assert client.patch("/outputs/out_nope/select").status_code == 404


def test_run_qa_scores_an_unscored_output(client):
    """An output with no QA score can be scored on demand, unlocking retry."""
    from app.database import engine as db_engine
    from app.models.render_job import RenderJob, RenderStatus
    from app.models.render_output import RenderOutput

    # Seed a succeeded job + output with a real video file but NO score.
    from app.config import get_settings

    settings = get_settings()
    settings.ensure_dirs()
    video = settings.outputs_dir / "manual_qa.mp4"
    video.write_bytes(b"fake-mp4")

    # The stored spec lets retry rebuild the RenderSpec after QA records issues.
    spec = {
        "scene_id": "scene_x",
        "duration": 5,
        "prompt": "@Image p",
        "reference_images": [{"name": "Image", "asset_id": "asset_ref"}],
    }
    with Session(db_engine) as s:
        job = RenderJob(
            id="job_unscored",
            scene_id="scene_x",
            status=RenderStatus.succeeded,
            request_json={"prompt": "@Image p", "multi_shot": True, "spec": spec},
        )
        s.add(job)
        out = RenderOutput(
            id="out_unscored", render_job_id="job_unscored", video_path=str(video)
        )
        s.add(out)
        s.commit()

    # QA agent returns issues so the Fix flow is unlocked.
    from app.schemas import QAResult

    client.fake_llm.qa = QAResult(
        score=4, passed=False, issues=["face distorted"], recommendation="regenerate"
    )
    resp = client.post("/outputs/out_unscored/run-qa")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["score"] == 4
    assert data["qa_issues"] == ["face distorted"]

    # Now retry is unlocked (issues recorded).
    assert client.post("/outputs/out_unscored/retry").status_code == 202


def test_run_qa_unknown_output_404(client):
    assert client.post("/outputs/out_nope/run-qa").status_code == 404


def test_resubmit_failed_job_replays_stored_spec(client):
    """A FAILED job can be resubmitted verbatim from its stored spec."""
    from app.database import engine as db_engine
    from app.models.render_job import RenderJob, RenderStatus

    spec = {
        "scene_id": "scene_x",
        "duration": 5,
        "prompt": "@Image hero",
        "reference_images": [{"name": "Image", "asset_id": "asset_ref"}],
        "sound": True,
        "keep_original_sound": True,
        "multi_shot": True,
        "shot_type": "intelligence",
    }
    # Seed a FAILED job carrying its spec (as start_render would have stored).
    with Session(db_engine) as s:
        job = RenderJob(
            id="job_failed",
            scene_id="scene_x",
            provider="atlascloud",
            status=RenderStatus.failed,
            error="ret:1000 internal error",
            request_json={"spec": spec},
        )
        s.add(job)
        s.commit()

    resp = client.post("/render-jobs/job_failed/resubmit")
    assert resp.status_code == 202, resp.text
    new_job_id = resp.json()["job_id"]
    assert new_job_id != "job_failed"
    body = _wait_for_job(client, new_job_id)
    assert body["job"]["status"] == "succeeded", body
    # The replayed payload carries the same prompt (verbatim, no corrections).
    assert client.fake_atlas.payloads[-1]["prompt"] == "@Image hero"


def test_resubmit_job_without_spec_rejected(client):
    from app.database import engine as db_engine
    from app.models.render_job import RenderJob, RenderStatus

    with Session(db_engine) as s:
        s.add(RenderJob(id="job_nospec", status=RenderStatus.failed, request_json={}))
        s.commit()
    assert client.post("/render-jobs/job_nospec/resubmit").status_code == 422
    assert client.post("/render-jobs/job_missing/resubmit").status_code == 404


def test_successful_job_records_done_stage(client):
    _, body, _ = _finished_output(client)
    assert body["job"]["stage"] == "done"
    assert body["job"]["progress"] == "Done"


def test_failed_job_records_humanized_progress(client, monkeypatch):
    """A provider 'failed' status with a known ret: code lands a human-readable
    progress label and a failed stage on the job."""
    from app.providers.atlascloud_video import AtlasCloudVideoProvider

    async def failing_poll(self, job_id):
        from app.providers.base import PollResult

        return PollResult(
            status="failed",
            output_urls=[],
            error="ret:1201 max number is 7",
            raw={"status": "failed", "error": "ret:1201 max number is 7"},
        )

    monkeypatch.setattr(AtlasCloudVideoProvider, "poll", failing_poll)

    spec = {
        "scene_id": "scene_x",
        "duration": 5,
        "prompt": "@Image p",
        "reference_images": [{"name": "Image", "asset_id": "asset_ref"}],
    }
    job_id = client.post("/render", json=spec).json()["job_id"]
    body = _wait_for_job(client, job_id)
    assert body["job"]["status"] == "failed", body
    assert body["job"]["stage"] == "failed"
    # Humanized progress, not the raw ret: code.
    assert "reference image" in body["job"]["progress"].lower()
    # Raw error is preserved for diagnostics.
    assert "ret:1201" in body["job"]["error"]
