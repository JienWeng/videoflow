"""End-to-end text pipeline with a mocked LLM (no network / API key needed)."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import create_app
from app.schemas import (
    AssetMetadata,
    CharacterBible,
    RenderSpec,
    SceneSpec,
    ScriptDraft,
    ScriptScene,
    ShotList,
    ShotSpec,
)


class FakeLLM:
    """Returns canned, schema-valid objects keyed by response_model."""

    async def generate(self, *, response_model, user_prompt, agent=None, context=None, **kw):
        name = response_model.__name__
        if name == "AssetMetadata":
            return AssetMetadata(
                asset_id="x", asset_type="prop", name="Lipstick",
                tags=["product", "red"], description="A red lipstick bullet.",
            )
        if name == "CharacterBible":
            return CharacterBible(
                character_id="x", name="Ava", appearance="tall, red scarf",
                personality="calm", visual_rules=["always wears red scarf"],
                voice_rules=["low calm voice"], reference_asset_ids=[],
            )
        if name == "ScriptDraft":
            return ScriptDraft(
                title="Bloom", summary="A lipstick comes alive.",
                scenes=[ScriptScene(scene_id="s1", title="Color River",
                                    summary="Color streaks across black.", suggested_duration=5)],
            )
        if name == "SceneSpec":
            return SceneSpec(
                scene_id="s1", title="Color River", summary="Color streaks across black.",
                duration=5, aspect_ratio="16:9", character_ids=[], asset_ids=[],
                shots=[ShotSpec(shot_id="sh1", duration=5, prompt="streak", camera="macro", movement="push-in")],
            )
        if name == "ShotList":
            return ShotList(scene_id="s1", shots=[
                ShotSpec(shot_id="sh1", duration=3, prompt="streak", camera="macro", movement="push-in"),
                ShotSpec(shot_id="sh2", duration=2, prompt="bloom", camera="wide", movement="static"),
            ])
        if name == "RenderSpec":
            return RenderSpec(scene_id="s1", shot_id="sh1", duration=5, prompt="@Image streak")
        raise AssertionError(f"unexpected response_model {name}")


@pytest.fixture
def client(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    import app.models  # noqa: F401
    SQLModel.metadata.create_all(engine)

    monkeypatch.setattr("app.agents.base.get_llm_client", lambda: FakeLLM())
    monkeypatch.setattr("app.config.Settings.ensure_dirs", lambda self: None)
    monkeypatch.setattr(
        "app.services.asset_service.get_settings",
        lambda: type("S", (), {"assets_dir": tmp_path, "ensure_dirs": lambda s=None: None})(),
    )

    app = create_app()

    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session
    return TestClient(app)


def test_full_text_pipeline(client):
    # character + bible
    cid = client.post("/characters", json={"name": "Ava"}).json()["id"]
    bible = client.post(f"/characters/{cid}/bible", json={"notes": "wears red scarf"}).json()
    assert "always wears red scarf" in bible["visual_rules_json"]

    # script -> scenes persisted
    draft = client.post("/scripts/generate", json={"idea": "a lipstick comes alive"}).json()
    assert draft["draft"]["title"] == "Bloom"
    scenes = draft["scenes"]
    assert len(scenes) == 1
    scene_id = scenes[0]["id"]

    # expand scene
    expanded = client.post(f"/scenes/{scene_id}/generate", json={"character_ids": []}).json()
    assert expanded["duration"] == 5
    assert expanded["scene_json"]["shots"]

    # shots persisted
    shots = client.post(f"/scenes/{scene_id}/shots/generate").json()
    assert len(shots) == 2
    listed = client.get(f"/scenes/{scene_id}/shots").json()
    assert [s["shot_order"] for s in listed] == [0, 1]


def test_asset_upload_and_recognise(client):
    files = {"file": ("lipstick.png", io.BytesIO(b"fakebytes"), "image/png")}
    asset = client.post("/assets/upload", files=files, data={"asset_type": "prop"}).json()
    aid = asset["id"]
    recognised = client.post(f"/assets/{aid}/recognise", json={"description": "a red lipstick"}).json()
    assert recognised["name"] == "Lipstick"
    assert "product" in recognised["tags_json"]
