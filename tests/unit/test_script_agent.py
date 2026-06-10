"""Script agent: scene_count parameter flows into the prompt."""

from __future__ import annotations

import pytest

from app.agents.script_agent import generate_script
from app.schemas import ScriptDraft
from app.schemas.scene_schema import ScriptScene


def _make_draft(n: int) -> ScriptDraft:
    return ScriptDraft(
        title="Test Video",
        summary="A test summary",
        scenes=[
            ScriptScene(
                scene_id=f"s{i}",
                title=f"Scene {i}",
                summary=f"Summary {i}",
                suggested_duration=5,
            )
            for i in range(1, n + 1)
        ],
    )


class FakeLLM:
    def __init__(self, result: ScriptDraft):
        self.result = result
        self.calls: list[dict] = []

    async def generate(self, *, agent, response_model, user_prompt, context=None, images=None):
        self.calls.append({"agent": agent, "user_prompt": user_prompt})
        assert response_model is ScriptDraft
        return self.result


@pytest.mark.asyncio
async def test_scene_count_appears_in_prompt():
    """When scene_count is given, 'EXACTLY 1' (or similar) must appear in the prompt."""
    fake = FakeLLM(_make_draft(3))
    await generate_script(idea="a cat story", scene_count=1, client=fake)
    prompt = fake.calls[0]["user_prompt"]
    # The prompt must instruct the LLM to produce exactly 1 scene
    assert "EXACTLY 1" in prompt or "exactly 1" in prompt


@pytest.mark.asyncio
async def test_scene_count_not_in_prompt_when_unset():
    """When scene_count is None, no 'EXACTLY' instruction is added."""
    fake = FakeLLM(_make_draft(3))
    await generate_script(idea="a dog story", client=fake)
    prompt = fake.calls[0]["user_prompt"]
    assert "EXACTLY" not in prompt


@pytest.mark.asyncio
async def test_scene_count_5_appears_in_prompt():
    """scene_count=5 produces 'EXACTLY 5' in the prompt."""
    fake = FakeLLM(_make_draft(3))
    await generate_script(idea="an epic story", scene_count=5, client=fake)
    prompt = fake.calls[0]["user_prompt"]
    assert "EXACTLY 5" in prompt or "exactly 5" in prompt
