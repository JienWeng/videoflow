"""Unit tests for the refine agent (AI-assisted scene/shot editing)."""

from __future__ import annotations

from app.agents.refine_agent import refine_scene, refine_shot
from app.llm.prompts import PROMPTS
from app.schemas import SceneRefinement, ShotRefinement


class FakeLLM:
    def __init__(self, result):
        self.result = result
        self.agent: str | None = None
        self.response_model = None
        self.user_prompt: str | None = None

    async def generate(self, *, agent, response_model, user_prompt, context=None, images=None):
        self.agent = agent
        self.response_model = response_model
        self.user_prompt = user_prompt
        return self.result


class TestRefineScene:
    async def test_entity_and_instruction_reach_the_prompt(self):
        llm = FakeLLM(SceneRefinement(summary="warmer dusk lighting", note="warmed it"))
        scene = {
            "title": "Meadow lesson",
            "summary": "a sunny meadow lesson",
            "duration": 6,
            "aspect_ratio": "9:16",
        }
        result = await refine_scene(scene=scene, instruction="make the lighting warmer", client=llm)
        assert llm.agent == "refine_agent"
        assert llm.response_model is SceneRefinement
        assert "a sunny meadow lesson" in llm.user_prompt
        assert "make the lighting warmer" in llm.user_prompt
        assert result.summary == "warmer dusk lighting"
        assert result.title is None  # untouched fields stay None


class TestRefineShot:
    async def test_shot_scene_context_and_instruction_reach_the_prompt(self):
        llm = FakeLLM(ShotRefinement(prompt="Grace waves slowly", note="slowed it"))
        shot = {
            "prompt": "Grace waves at camera",
            "duration": 3,
            "camera": "mid",
            "movement": "static",
        }
        result = await refine_shot(
            shot=shot,
            scene_summary="a sunny meadow lesson",
            instruction="make the wave slower",
            client=llm,
        )
        assert llm.agent == "refine_agent"
        assert llm.response_model is ShotRefinement
        assert "Grace waves at camera" in llm.user_prompt
        assert "a sunny meadow lesson" in llm.user_prompt
        assert "make the wave slower" in llm.user_prompt
        assert result.prompt == "Grace waves slowly"
        assert result.camera is None


class TestRefinePromptRules:
    def test_refine_prompt_carries_production_rules(self):
        prompt = PROMPTS["refine_agent"]
        assert "post-production" in prompt
        assert "「」" in prompt
        assert "ONE multi-shot video" in prompt
