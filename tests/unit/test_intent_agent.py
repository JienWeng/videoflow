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
async def test_intent_defaults_are_safe():
    intent = Intent()
    assert intent.action == IntentAction.unknown
    assert intent.confidence == 0.0
