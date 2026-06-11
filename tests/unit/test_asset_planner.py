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

async def test_plan_assets_shots_block_reaches_prompt():
    from app.agents.asset_planner import plan_assets

    llm = FakeLLM(AssetPlan())
    await plan_assets(
        scene_summary="s",
        scene_json={},
        existing_assets=[],
        shots=[
            {"shot_order": 0, "prompt": "Grace waves at camera"},
            {"shot_order": 1, "prompt": "Grace points at the meadow"},
        ],
        client=llm,
    )
    assert "Scene shots" in llm.user_prompt
    assert "Grace waves at camera" in llm.user_prompt
    assert "Grace points at the meadow" in llm.user_prompt


async def test_plan_assets_without_shots_omits_shots_block():
    from app.agents.asset_planner import plan_assets

    llm = FakeLLM(AssetPlan())
    await plan_assets(scene_summary="s", scene_json={}, existing_assets=[], client=llm)
    assert "Scene shots" not in llm.user_prompt


async def test_plan_assets_characters_and_story_blocks_reach_prompt():
    from app.agents.asset_planner import plan_assets

    llm = FakeLLM(AssetPlan())
    await plan_assets(
        scene_summary="s",
        scene_json={},
        existing_assets=[],
        characters=[{"name": "Grace", "appearance": "small girl in a pink dress"}],
        story={
            "story": {"idea": "a cat learns to fly", "title": "Sky Cat", "summary": "x"},
            "other_scenes": [{"title": "Takeoff", "summary": "the cat jumps"}],
        },
        client=llm,
    )
    assert "Cast (props must fit these characters)" in llm.user_prompt
    assert "Grace" in llm.user_prompt
    assert "small girl in a pink dress" in llm.user_prompt
    assert "Overall story and sibling scenes (keep continuity)" in llm.user_prompt
    assert "a cat learns to fly" in llm.user_prompt


async def test_plan_assets_omits_characters_and_story_blocks_when_absent():
    from app.agents.asset_planner import plan_assets

    llm = FakeLLM(AssetPlan())
    await plan_assets(scene_summary="s", scene_json={}, existing_assets=[], client=llm)
    assert "Cast (props must fit these characters)" not in llm.user_prompt
    assert "Overall story and sibling scenes" not in llm.user_prompt


def test_planned_asset_shot_orders_defaults_empty():
    assert PlannedAsset(name="Cup", image_prompt="a cup").shot_orders == []


def test_planned_asset_reuse_defaults_false():
    assert PlannedAsset(name="Cup", image_prompt="a cup").reuse is False


async def test_plan_assets_library_block_reaches_prompt():
    from app.agents.asset_planner import plan_assets

    llm = FakeLLM(AssetPlan())
    await plan_assets(
        scene_summary="s",
        scene_json={},
        existing_assets=[],
        library=[{"name": "Red Cup", "type": "prop", "description": "a red cup"}],
        client=llm,
    )
    assert "Asset library" in llm.user_prompt
    assert "REUSE" in llm.user_prompt
    assert "Red Cup" in llm.user_prompt


async def test_plan_assets_without_library_omits_library_block():
    from app.agents.asset_planner import plan_assets

    llm = FakeLLM(AssetPlan())
    await plan_assets(scene_summary="s", scene_json={}, existing_assets=[], client=llm)
    assert "Asset library" not in llm.user_prompt


def test_asset_planner_prompt_mentions_library_reuse():
    from app.llm.prompts import PROMPTS

    prompt = PROMPTS["asset_planner"]
    assert "EXACT NAME" in prompt
    assert "librar" in prompt.lower()


class TestSplitReuse:
    """Cross-scene reuse routing: planned assets whose normalized name matches a
    global library asset are linked instead of regenerated."""

    @staticmethod
    def _planned(*names: str):
        return [PlannedAsset(name=n, image_prompt=f"an image of {n}") for n in names]

    def test_exact_match_routes_to_reuse(self):
        from app.services.asset_gen_service import split_reuse

        planned = self._planned("Red Cup")
        to_reuse, to_generate = split_reuse(planned, {"Red Cup": "asset_1"})
        assert to_reuse == [(planned[0], "asset_1")]
        assert to_generate == []

    def test_case_and_whitespace_normalized_match(self):
        from app.services.asset_gen_service import split_reuse

        planned = self._planned("red  CUP")
        to_reuse, to_generate = split_reuse(planned, {"Red\tCup ": "asset_1"})
        assert to_reuse == [(planned[0], "asset_1")]
        assert to_generate == []

    def test_novel_routes_to_generate(self):
        from app.services.asset_gen_service import split_reuse

        planned = self._planned("Lantern")
        to_reuse, to_generate = split_reuse(planned, {"Red Cup": "asset_1"})
        assert to_reuse == []
        assert to_generate == planned

    def test_order_preserved_in_both_lists(self):
        from app.services.asset_gen_service import split_reuse

        planned = self._planned("A", "B", "C", "D")
        library = {"B": "asset_b", "D": "asset_d"}
        to_reuse, to_generate = split_reuse(planned, library)
        assert [(p.name, a) for p, a in to_reuse] == [("B", "asset_b"), ("D", "asset_d")]
        assert [p.name for p in to_generate] == ["A", "C"]

    def test_empty_library_generates_everything(self):
        from app.services.asset_gen_service import split_reuse

        planned = self._planned("Red Cup", "Lantern")
        to_reuse, to_generate = split_reuse(planned, {})
        assert to_reuse == []
        assert to_generate == planned


class TestTagPrompt:
    def test_name_present_first_occurrence_replaced(self):
        from app.services.asset_gen_service import tag_prompt

        out = tag_prompt("Grace lifts the Red Cup, the Red Cup shines", "Red Cup")
        assert out == "Grace lifts the @Red Cup, the Red Cup shines"

    def test_name_absent_appended(self):
        from app.services.asset_gen_service import tag_prompt

        assert tag_prompt("Grace waves at camera", "Red Cup") == (
            "Grace waves at camera, featuring @Red Cup"
        )

    def test_already_tagged_unchanged(self):
        from app.services.asset_gen_service import tag_prompt

        prompt = "Grace lifts the @Red Cup"
        assert tag_prompt(prompt, "Red Cup") == prompt

    def test_substring_of_longer_word_not_corrupted(self):
        from app.services.asset_gen_service import tag_prompt

        # "Cup" must not splice into "Cupboard"; falls back to appending.
        assert tag_prompt("She opens the Cupboard", "Cup") == (
            "She opens the Cupboard, featuring @Cup"
        )

    def test_cjk_name_embedded_in_longer_word_appended(self):
        from app.services.asset_gen_service import tag_prompt

        assert tag_prompt("小红帽走进森林", "红帽") == "小红帽走进森林, featuring @红帽"


class TestDedupPlanned:
    """Code-level planner dedup: the LLM is asked not to duplicate existing
    assets, but we never trust it — dedup_planned enforces it deterministically."""

    @staticmethod
    def _planned(*names: str):
        return [PlannedAsset(name=n, image_prompt=f"an image of {n}") for n in names]

    def test_exact_duplicate_dropped(self):
        from app.services.asset_gen_service import dedup_planned

        out = dedup_planned(self._planned("Meadow", "Red Cup"), ["Meadow"])
        assert [a.name for a in out] == ["Red Cup"]

    def test_case_insensitive_duplicate_dropped(self):
        from app.services.asset_gen_service import dedup_planned

        out = dedup_planned(self._planned("MEADOW", "Red Cup"), ["meadow"])
        assert [a.name for a in out] == ["Red Cup"]

    def test_whitespace_normalized_duplicate_dropped(self):
        from app.services.asset_gen_service import dedup_planned

        out = dedup_planned(self._planned("Red  Cup"), ["red cup"])
        assert out == []
        out2 = dedup_planned(self._planned("  red cup "), ["Red\tCup"])
        assert out2 == []

    def test_novel_assets_kept_order_preserved(self):
        from app.services.asset_gen_service import dedup_planned

        out = dedup_planned(
            self._planned("Red Cup", "Meadow", "Picnic Blanket"), ["Meadow"]
        )
        assert [a.name for a in out] == ["Red Cup", "Picnic Blanket"]

    def test_no_existing_names_keeps_everything(self):
        from app.services.asset_gen_service import dedup_planned

        planned = self._planned("Red Cup", "Picnic Blanket")
        assert dedup_planned(planned, []) == planned
