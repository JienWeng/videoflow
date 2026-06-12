"""Intent agent: catalog goes into the prompt; LLM output passes through."""

from __future__ import annotations

import pytest

from app.agents.intent_agent import classify_intent
from app.schemas import Intent, IntentAction


class FakeLLM:
    def __init__(self, result: Intent):
        self.result = result
        self.calls: list[dict] = []

    async def generate(self, *, agent, response_model, user_prompt, context=None, images=None):
        self.calls.append({"agent": agent, "user_prompt": user_prompt})
        assert response_model is Intent
        return self.result


@pytest.mark.asyncio
async def test_catalog_and_message_reach_the_prompt():
    fake = FakeLLM(Intent(action=IntentAction.storyboard, scene_id="scene_1",
                          confidence=0.9, reply="ok"))
    out = await classify_intent(
        message="给乐乐的场景生成分镜图",
        scenes=[{"id": "scene_1", "title": "我是乐乐"}],
        characters=[{"id": "char_1", "name": "乐乐"}],
        client=fake,
    )
    assert out.action == IntentAction.storyboard
    prompt = fake.calls[0]["user_prompt"]
    assert "给乐乐的场景生成分镜图" in prompt
    assert "scene_1" in prompt and "我是乐乐" in prompt
    assert "char_1" in prompt and "乐乐" in prompt
    assert fake.calls[0]["agent"] == "intent_agent"


@pytest.mark.asyncio
async def test_retry_render_intent_round_trip():
    fake = FakeLLM(Intent(action=IntentAction.retry_render, output_id="out_1",
                          confidence=0.9, reply="ok"))
    out = await classify_intent(
        message="这个视频脸崩了，帮我修一下重新渲染",
        scenes=[],
        characters=[],
        outputs=[{"id": "out_1", "video": "scene_1.mp4"}],
        client=fake,
    )
    assert out.action == IntentAction.retry_render
    assert out.output_id == "out_1"
    assert "out_1" in fake.calls[0]["user_prompt"]


def test_intent_prompt_mentions_retry_render():
    from app.llm.prompts import PROMPTS

    assert "retry_render" in PROMPTS["intent_agent"]


def test_intent_prompt_mentions_new_actions():
    from app.llm.prompts import PROMPTS

    prompt = PROMPTS["intent_agent"]
    for action in ("refine_scene", "refine_shot", "delete_scene",
                   "style_ingest", "plan_assets"):
        assert action in prompt, action


@pytest.mark.asyncio
async def test_state_and_history_blocks_reach_the_prompt():
    fake = FakeLLM(Intent(action=IntentAction.unknown, reply="ok"))
    await classify_intent(
        message="然后呢？",
        scenes=[],
        characters=[],
        history=[
            {"role": "user", "text": "帮我做个视频"},
            {"role": "assistant", "text": "先上传角色照片吧"},
        ],
        state={"characters": 0, "has_style": False, "scripts": 0,
               "scenes": [], "next_steps": ["Add characters"]},
        client=fake,
    )
    prompt = fake.calls[0]["user_prompt"]
    assert "Conversation so far" in prompt
    assert "先上传角色照片吧" in prompt
    assert "Project state" in prompt
    assert "next_steps" in prompt


@pytest.mark.asyncio
async def test_state_and_history_blocks_omitted_when_absent():
    fake = FakeLLM(Intent(action=IntentAction.unknown, reply="ok"))
    await classify_intent(message="hi", scenes=[], characters=[], client=fake)
    prompt = fake.calls[0]["user_prompt"]
    assert "Conversation so far" not in prompt
    assert "Project state" not in prompt


def test_intent_prompt_mentions_project_state_and_lost_user_rule():
    from app.llm.prompts import PROMPTS

    prompt = PROMPTS["intent_agent"]
    assert "project state" in prompt.lower()
    assert "next_steps" in prompt
    assert "prerequisite" in prompt.lower()


@pytest.mark.asyncio
async def test_intent_defaults_are_safe():
    intent = Intent()
    assert intent.action == IntentAction.unknown
    assert intent.confidence == 0.0
