"""Unit tests for the style agent — context blocks reach the prompt."""

from __future__ import annotations

from app.schemas import StyleSpec


class FakeLLM:
    def __init__(self):
        self.agent: str | None = None
        self.user_prompt: str | None = None

    async def generate(self, *, agent, response_model, user_prompt, context=None, images=None):
        assert response_model is StyleSpec
        self.agent = agent
        self.user_prompt = user_prompt
        return StyleSpec(
            style_prompt="3D cartoon render, soft shapes, high detail",
            palette="soft pastel, warm yellows",
            lighting="bright morning sunlight",
            audience="children 2-6",
            tone="playful, gentle",
            reasoning="derived from the meadow scenes",
        )


async def test_derive_style_passes_context_blocks_and_agent_name():
    from app.agents.style_agent import derive_style

    llm = FakeLLM()
    spec = await derive_style(
        scenes=[{"title": "Meadow Lesson", "summary": "a sunny meadow lesson", "aspect_ratio": "9:16"}],
        characters=[{"name": "Grace", "appearance": "girl in pink dress"}],
        assets=[{"name": "Meadow", "description": "a green meadow background"}],
        client=llm,
    )
    assert llm.agent == "style_agent"
    # All three context blocks reach the user prompt.
    assert "Meadow Lesson" in llm.user_prompt
    assert "a sunny meadow lesson" in llm.user_prompt
    assert "girl in pink dress" in llm.user_prompt
    assert "a green meadow background" in llm.user_prompt
    assert spec.style_prompt == "3D cartoon render, soft shapes, high detail"
    assert spec.palette == "soft pastel, warm yellows"


async def test_derive_style_includes_scripts_block():
    from app.agents.style_agent import derive_style

    llm = FakeLLM()
    await derive_style(
        scenes=[],
        characters=[],
        assets=[],
        scripts=[{"idea": "a cat learns to fly", "title": "Sky Cat",
                  "summary": "a cat's flying journey"}],
        client=llm,
    )
    assert "Scripts (overall story)" in llm.user_prompt
    assert "a cat learns to fly" in llm.user_prompt
    assert "Sky Cat" in llm.user_prompt


def test_style_agent_prompt_and_skill_registered():
    from app.llm.prompts import PROMPTS
    from app.llm.skills import SKILLS

    assert "style_agent" in PROMPTS
    assert "art director" in PROMPTS["style_agent"]
    skill = SKILLS["style_agent"]
    assert skill.temperature == 0.3
