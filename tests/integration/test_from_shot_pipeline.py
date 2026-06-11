"""POST /render/from-shot — verifies character reference images AND shot assets
all reach the Kling payload images[], with multi-shot + voice enforced."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.database import get_session
from app.schemas import QAResult, RenderSpec


class FakeLLM:
    """Prompt agent returns the worst-case drifting spec (voice off, ALL refs
    dropped) so the test proves the pipeline restores them itself; QA passes."""

    def __init__(self):
        self.render_prompts: list[str] = []

    async def generate(self, *, agent, response_model, user_prompt, context=None, images=None):
        if response_model is RenderSpec:
            self.render_prompts.append(user_prompt)
            return RenderSpec(
                scene_id="ignored",
                duration=5,
                prompt="@Grace waves by @Meadow",
                sound=False,
                keep_original_sound=False,
            )
        assert response_model is QAResult
        return QAResult(score=8, passed=True, issues=[], recommendation="accept")


class FakeAtlas:
    def __init__(self):
        self.video_payloads: list[dict] = []

    async def upload_media(self, file_path: str) -> str:
        return f"https://static.atlascloud.ai/up/{Path(file_path).name}"

    async def generate_video(self, payload: dict) -> str:
        self.video_payloads.append(payload)
        return "pred_1"

    async def get_prediction(self, pid: str) -> dict:
        return {"status": "completed", "outputs": ["https://static.atlascloud.ai/out.mp4"]}


@pytest.fixture
def ctx(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr("app.services.poll_service.engine", engine)
    monkeypatch.setattr("app.jobs.worker.reconcile_pending", lambda: 0)

    fake_atlas = FakeAtlas()
    monkeypatch.setattr("app.services.render_service.get_atlas_client", lambda: fake_atlas)
    monkeypatch.setattr("app.providers.atlascloud_video.get_atlas_client", lambda: fake_atlas)
    fake_llm = FakeLLM()
    monkeypatch.setattr("app.agents.base.get_llm_client", lambda: fake_llm)

    async def fake_download(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-mp4")
        return dest

    async def fake_thumb(video_path, dest, **kw):
        return None

    monkeypatch.setattr("app.services.media.download", fake_download)
    monkeypatch.setattr("app.services.poll_service.media.download", fake_download)
    monkeypatch.setattr("app.services.poll_service.media.make_thumbnail", fake_thumb)

    from app.models import Asset, Character, Scene, Shot

    for name in ("char.png", "char2.png", "grace_photo.png", "bg.png"):
        (tmp_path / name).write_bytes(b"img")
    with Session(engine) as s:
        # Grace has TWO reference sheets, and the shot carries ANOTHER photo of
        # her ("Grace" asset) — only the first sheet may reach Kling, or the
        # model renders her twice (clone bug).
        s.add(Character(
            id="char_grace", name="Grace",
            reference_asset_ids_json=["asset_char", "asset_char2"],
        ))
        s.add(Asset(id="asset_char", type="character_reference", name="Grace",
                    file_path=str(tmp_path / "char.png")))
        s.add(Asset(id="asset_char2", type="character_reference", name="Grace",
                    file_path=str(tmp_path / "char2.png")))
        s.add(Asset(id="asset_grace_photo", type="prop", name="Grace",
                    file_path=str(tmp_path / "grace_photo.png")))
        s.add(Asset(id="asset_bg", type="background", name="Meadow",
                    file_path=str(tmp_path / "bg.png")))
        s.add(Scene(id="scene_1", title="t", summary="sum", duration=5,
                    character_ids_json=["char_grace"]))
        s.add(Shot(id="shot_1", scene_id="scene_1", shot_order=0, duration=5,
                   prompt="Grace waves", camera="mid-shot", movement="static",
                   asset_ids_json=["asset_bg", "asset_grace_photo"]))
        s.commit()

    from app.main import create_app

    app = create_app()

    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as c:
        yield c, fake_atlas, fake_llm


def test_from_shot_sends_characters_and_assets_with_multishot_voice(ctx):
    client, fake_atlas, fake_llm = ctx
    resp = client.post(
        "/render/from-shot", json={"scene_id": "scene_1", "shot_id": "shot_1"}
    )
    assert resp.status_code == 202, resp.text

    payload = fake_atlas.video_payloads[0]
    # Exactly ONE image for Grace (first sheet only) plus the background:
    # her second sheet and the shot's extra photo of her are dropped so Kling
    # never sees two named refs of the same person (clone bug).
    assert payload["images"] == [
        "https://static.atlascloud.ai/up/char.png",
        "https://static.atlascloud.ai/up/bg.png",
    ]
    # No "Grace 2" reference was ever shown to the prompt agent.
    assert "Grace 2" not in fake_llm.render_prompts[0]
    # Voice + multi-shot enforced even though the LLM turned them off.
    assert payload["sound"] is True
    assert payload["keep_original_sound"] is True
    assert payload["multi_shot"] is True
    assert payload["shot_type"] == "intelligence"


def test_from_shot_passes_story_context_to_prompt_agent(ctx, monkeypatch):
    """The from-shot endpoint must feed scene_service.story_context into the
    prompt agent: a sentinel story dict must land in the LLM's user prompt."""
    client, _, fake_llm = ctx
    sentinel = {"story": {"idea": "STORY-SENTINEL-7", "title": "t", "summary": "s"}}
    monkeypatch.setattr(
        "app.services.scene_service.story_context", lambda session, scene: sentinel
    )

    resp = client.post(
        "/render/from-shot", json={"scene_id": "scene_1", "shot_id": "shot_1"}
    )
    assert resp.status_code == 202, resp.text
    assert fake_llm.render_prompts
    prompt = fake_llm.render_prompts[-1]
    assert "Overall story and sibling scenes (keep continuity)" in prompt
    assert "STORY-SENTINEL-7" in prompt
