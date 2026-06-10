"""Unit tests for the asset-planner agent (scene props/backgrounds planning)."""

from __future__ import annotations

from app.schemas import AssetPlan, PlannedAsset


class FakeLLM:
    def __init__(self, plan: AssetPlan):
        self.plan = plan
        self.agent: str | None = None
        self.user_prompt: str | None = None

    async def generate(self, *, agent, response_model, user_prompt, context=None, images=None):
        assert response_model is AssetPlan
        self.agent = agent
        self.user_prompt = user_prompt
        return self.plan


async def test_plan_assets_shows_scene_existing_assets_and_instruction():
    from app.agents.asset_planner import plan_assets

    plan = AssetPlan(
        assets=[
            PlannedAsset(
                name="Red Cup",
                asset_type="prop",
                description="a shiny red cup",
                image_prompt="a shiny red ceramic cup, warm morning light, 3D cartoon style",
            )
        ],
        reasoning="the scene needs a red cup",
    )
    llm = FakeLLM(plan)
    result = await plan_assets(
        scene_summary="a sunny meadow lesson",
        scene_json={"setting": "sunny meadow", "lighting": "warm daylight"},
        existing_assets=[{"name": "Meadow", "type": "background", "description": ""}],
        instruction="the cup looks wrong, make a red one",
        client=llm,
    )

    assert result is plan
    assert llm.agent == "asset_planner"
    # Scene summary, scene spec, existing asset names and the user's wish all
    # reach the prompt so the planner doesn't duplicate or drift in style.
    assert "a sunny meadow lesson" in llm.user_prompt
    assert "warm daylight" in llm.user_prompt
    assert "Meadow" in llm.user_prompt
    assert "the cup looks wrong, make a red one" in llm.user_prompt


async def test_plan_assets_without_instruction_omits_instruction_block():
    from app.agents.asset_planner import plan_assets

    llm = FakeLLM(AssetPlan())
    result = await plan_assets(
        scene_summary="s",
        scene_json={},
        existing_assets=[],
        client=llm,
    )
    assert result.assets == []
    assert "Instruction" not in llm.user_prompt


def test_asset_planner_skill_and_prompt_registered():
    from app.llm.prompts import PROMPTS
    from app.llm.skills import get_skill

    skill = get_skill("asset_planner")
    assert skill is not None
    assert skill.temperature == 0.4
    prompt = PROMPTS["asset_planner"]
    # Core rules: no duplicates, standalone image prompts, no on-screen text.
    assert "exist" in prompt.lower()
    assert "text" in prompt.lower()
