"""POST /chat — guided intent: LLM classifies, service validates ids, response
carries the options needed to build a pre-filled action card."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.database import get_session
from app.schemas import Intent, IntentAction


class FakeLLM:
    def __init__(self, intent: Intent):
        self.intent = intent
        self.prompts: list[str] = []

    async def generate(self, *, agent, response_model, user_prompt, context=None, images=None):
        assert response_model is Intent
        self.prompts.append(user_prompt)
        return self.intent


def make_client(monkeypatch, tmp_path, intent: Intent) -> TestClient:
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr("app.jobs.worker.reconcile_pending", lambda: 0)
    monkeypatch.setattr("app.agents.base.get_llm_client", lambda: FakeLLM(intent))

    from app.models import Character, Scene

    with Session(engine) as s:
        s.add(Scene(id="scene_1", title="我是乐乐", summary="x"))
        s.add(Character(id="char_1", name="乐乐"))
        s.commit()

    from app.main import create_app

    app = create_app()

    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session
    return TestClient(app)


def test_chat_returns_intent_and_options(monkeypatch, tmp_path):
    intent = Intent(action=IntentAction.storyboard, scene_id="scene_1",
                    confidence=0.9, reply="好的，为《我是乐乐》生成分镜图")
    with make_client(monkeypatch, tmp_path, intent) as client:
        r = client.post("/chat", json={"message": "给乐乐的场景生成分镜图"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"]["action"] == "storyboard"
    assert body["intent"]["scene_id"] == "scene_1"
    assert [s["id"] for s in body["options"]["scenes"]] == ["scene_1"]
    assert [c["id"] for c in body["options"]["characters"]] == ["char_1"]
    assert "kids" in body["options"]["caption_styles"]


def test_chat_discards_hallucinated_ids_and_low_confidence(monkeypatch, tmp_path):
    intent = Intent(action=IntentAction.render_scene, scene_id="scene_NOPE",
                    confidence=0.2, reply="…")
    with make_client(monkeypatch, tmp_path, intent) as client:
        r = client.post("/chat", json={"message": "随便说点什么"})
    body = r.json()
    assert body["intent"]["scene_id"] is None          # invalid id dropped
    assert body["intent"]["action"] == "unknown"        # confidence < 0.5


def test_chat_generate_assets_intent(monkeypatch, tmp_path):
    intent = Intent(action=IntentAction.generate_assets, scene_id="scene_1",
                    idea="red cup", confidence=0.9, reply="好的，为场景生成道具")
    with make_client(monkeypatch, tmp_path, intent) as client:
        r = client.post("/chat", json={"message": "the cup looks wrong, make a red one"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"]["action"] == "generate_assets"
    assert body["intent"]["scene_id"] == "scene_1"
    assert body["intent"]["idea"] == "red cup"


def test_chat_refine_scene_intent(monkeypatch, tmp_path):
    """refine_scene round-trip: the instruction rides in `idea`, scene resolved."""
    intent = Intent(action=IntentAction.refine_scene, scene_id="scene_1",
                    idea="make the lighting warmer", confidence=0.9,
                    reply="好的，让灯光更暖")
    with make_client(monkeypatch, tmp_path, intent) as client:
        r = client.post("/chat", json={"message": "把乐乐场景的灯光调暖一点"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"]["action"] == "refine_scene"
    assert body["intent"]["scene_id"] == "scene_1"
    assert body["intent"]["idea"] == "make the lighting warmer"


def test_chat_delete_scene_intent(monkeypatch, tmp_path):
    """delete_scene round-trip: action + scene_id survive validation (the card
    itself is the confirmation; chat never deletes anything)."""
    intent = Intent(action=IntentAction.delete_scene, scene_id="scene_1",
                    confidence=0.9, reply="确认后将删除该场景")
    with make_client(monkeypatch, tmp_path, intent) as client:
        r = client.post("/chat", json={"message": "删掉乐乐那个场景"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"]["action"] == "delete_scene"
    assert body["intent"]["scene_id"] == "scene_1"


def test_chat_plan_assets_intent(monkeypatch, tmp_path):
    """plan_assets round-trip: suggestion-only props planning intent."""
    intent = Intent(action=IntentAction.plan_assets, scene_id="scene_1",
                    idea="kitchen props", confidence=0.9,
                    reply="好的，为场景建议道具")
    with make_client(monkeypatch, tmp_path, intent) as client:
        r = client.post("/chat", json={"message": "这个场景还需要什么道具？"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"]["action"] == "plan_assets"
    assert body["intent"]["scene_id"] == "scene_1"
    assert body["intent"]["idea"] == "kitchen props"


def test_chat_scene_count_passes_through(monkeypatch, tmp_path):
    """Intent.scene_count is preserved end-to-end through the chat endpoint."""
    intent = Intent(
        action=IntentAction.generate_script,
        idea="一个关于小猫的视频",
        scene_count=1,
        confidence=0.9,
        reply="好的，为您生成一个场景的脚本",
    )
    with make_client(monkeypatch, tmp_path, intent) as client:
        r = client.post("/chat", json={"message": "帮我做一个视频，只要一个场景"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"]["action"] == "generate_script"
    assert body["intent"]["scene_count"] == 1


def test_chat_response_carries_state_with_next_steps(monkeypatch, tmp_path):
    """The fixture has 1 scene (stub) + 1 character — state must reflect that
    and next_steps must point at the scene's first missing pipeline step."""
    intent = Intent(action=IntentAction.unknown, reply="…")
    with make_client(monkeypatch, tmp_path, intent) as client:
        r = client.post("/chat", json={"message": "我现在该做什么？"})
    assert r.status_code == 200
    body = r.json()
    state = body["state"]
    assert state["characters"] == 1
    assert state["scenes"][0]["id"] == "scene_1"
    assert state["scenes"][0]["expanded"] is False
    assert state["next_steps"], "next_steps must never be empty here"
    assert "我是乐乐" in state["next_steps"][0]
    assert body["warnings"] == []


def test_chat_warns_generate_script_without_characters(monkeypatch, tmp_path):
    intent = Intent(action=IntentAction.generate_script, idea="小猫的故事",
                    confidence=0.9, reply="好的")
    with make_client(monkeypatch, tmp_path, intent) as client:
        # wipe the seeded character so the prerequisite is missing
        from app.models import Character

        eng = client.app.dependency_overrides[get_session]
        with next(eng()) as s:  # type: ignore[misc]
            s.delete(s.get(Character, "char_1"))
            s.commit()
        r = client.post("/chat", json={"message": "做一个小猫的视频"})
    body = r.json()
    assert body["intent"]["action"] == "generate_script"  # still classified
    assert body["warnings"], "missing-characters warning expected"
    assert "character" in body["warnings"][0].lower()


def test_chat_warns_storyboard_when_scene_has_no_shots(monkeypatch, tmp_path):
    intent = Intent(action=IntentAction.storyboard, scene_id="scene_1",
                    confidence=0.9, reply="好的")
    with make_client(monkeypatch, tmp_path, intent) as client:
        r = client.post("/chat", json={"message": "给乐乐的场景生成分镜图"})
    body = r.json()
    assert body["warnings"]
    assert "shot" in body["warnings"][0].lower()


def test_chat_warns_style_ingest_without_story(monkeypatch, tmp_path):
    intent = Intent(action=IntentAction.style_ingest, confidence=0.9, reply="好的")
    with make_client(monkeypatch, tmp_path, intent) as client:
        r = client.post("/chat", json={"message": "从故事里提取风格"})
    body = r.json()
    assert body["warnings"]
    assert "script" in body["warnings"][0].lower()


def test_chat_history_reaches_the_llm_prompt(monkeypatch, tmp_path):
    intent = Intent(action=IntentAction.unknown, reply="…")
    with make_client(monkeypatch, tmp_path, intent) as client:
        fake = FakeLLM(intent)
        monkeypatch.setattr("app.agents.base.get_llm_client", lambda: fake)
        r = client.post("/chat", json={
            "message": "好，就按你说的来",
            "history": [
                {"role": "user", "text": "帮我做个视频"},
                {"role": "assistant", "text": "建议先上传角色照片"},
            ],
        })
    assert r.status_code == 200
    prompt = fake.prompts[0]
    assert "Conversation so far" in prompt
    assert "建议先上传角色照片" in prompt


def test_chat_history_truncated_to_last_six_and_300_chars(monkeypatch, tmp_path):
    intent = Intent(action=IntentAction.unknown, reply="…")
    history = [{"role": "user", "text": f"msg-{i} " + "x" * 400}
               for i in range(10)]
    with make_client(monkeypatch, tmp_path, intent) as client:
        fake = FakeLLM(intent)
        monkeypatch.setattr("app.agents.base.get_llm_client", lambda: fake)
        r = client.post("/chat", json={"message": "hi", "history": history})
    assert r.status_code == 200
    prompt = fake.prompts[0]
    assert "msg-3" not in prompt          # only the last 6 survive
    assert "msg-4" in prompt and "msg-9" in prompt
    assert "x" * 301 not in prompt        # each text capped at 300 chars


def test_chat_llm_failure_degrades_to_unknown(monkeypatch, tmp_path):
    class Boom:
        async def generate(self, **kw):
            raise RuntimeError("llm down")

    with make_client(monkeypatch, tmp_path, Intent()) as client:
        monkeypatch.setattr("app.agents.base.get_llm_client", lambda: Boom())
        r = client.post("/chat", json={"message": "hi"})
    assert r.status_code == 200
    assert r.json()["intent"]["action"] == "unknown"
