"""Relationship-aware agent inputs: cast + linked-asset context blocks."""

from __future__ import annotations

from app.schemas import CharacterBible, SceneSpec, ShotList


class CapturingLLM:
    def __init__(self, result):
        self.result = result
        self.user_prompt: str | None = None

    async def generate(self, *, agent, response_model, user_prompt, context=None, images=None):
        self.user_prompt = user_prompt
        return self.result


GRACE = CharacterBible(
    character_id="char_grace",
    name="Grace",
    appearance="girl in pink dress",
    personality="cheerful",
    visual_rules=["always wears the pink dress"],
)
ASSETS = [
    {"name": "Red Cup", "type": "prop", "description": "a shiny red cup"},
    {"name": "Meadow", "type": "background", "description": "a sunny meadow"},
]


async def test_generate_shots_includes_cast_block():
    from app.agents.shot_agent import generate_shots

    scene = SceneSpec(scene_id="s1", title="t", summary="sum", duration=5)
    llm = CapturingLLM(ShotList(scene_id="s1"))
    await generate_shots(scene=scene, characters=[GRACE], client=llm)
    assert "Cast (use @Name to reference them)" in llm.user_prompt
    assert "Grace" in llm.user_prompt
    assert "girl in pink dress" in llm.user_prompt


async def test_generate_shots_includes_linked_assets_block():
    from app.agents.shot_agent import generate_shots

    scene = SceneSpec(scene_id="s1", title="t", summary="sum", duration=5)
    llm = CapturingLLM(ShotList(scene_id="s1"))
    await generate_shots(scene=scene, assets=ASSETS, client=llm)
    assert "Linked assets (use @Name)" in llm.user_prompt
    assert "Red Cup" in llm.user_prompt
    assert "a shiny red cup" in llm.user_prompt


async def test_generate_shots_omits_blocks_when_absent():
    from app.agents.shot_agent import generate_shots

    scene = SceneSpec(scene_id="s1", title="t", summary="sum", duration=5)
    llm = CapturingLLM(ShotList(scene_id="s1"))
    await generate_shots(scene=scene, client=llm)
    assert "Cast (use @Name to reference them)" not in llm.user_prompt
    assert "Linked assets (use @Name)" not in llm.user_prompt


async def test_generate_scene_includes_linked_assets_block():
    from app.agents.scene_agent import generate_scene

    llm = CapturingLLM(SceneSpec(scene_id="s1", title="t", summary="sum", duration=5))
    await generate_scene(
        scene_id="s1", title="t", summary="sum", suggested_duration=5,
        assets=ASSETS, client=llm,
    )
    assert "Linked assets (use @Name)" in llm.user_prompt
    assert "Meadow" in llm.user_prompt


async def test_generate_scene_omits_assets_block_when_absent():
    from app.agents.scene_agent import generate_scene

    llm = CapturingLLM(SceneSpec(scene_id="s1", title="t", summary="sum", duration=5))
    await generate_scene(scene_id="s1", title="t", summary="sum", suggested_duration=5, client=llm)
    assert "Linked assets (use @Name)" not in llm.user_prompt


STORY = {
    "story": {"idea": "a cat learns to fly", "title": "Sky Cat", "summary": "a cat's flying journey"},
    "other_scenes": [{"title": "Takeoff", "summary": "the cat jumps off the fence"}],
}


async def test_generate_scene_includes_story_block():
    from app.agents.scene_agent import generate_scene

    llm = CapturingLLM(SceneSpec(scene_id="s1", title="t", summary="sum", duration=5))
    await generate_scene(
        scene_id="s1", title="t", summary="sum", suggested_duration=5,
        story=STORY, client=llm,
    )
    assert "Overall story and sibling scenes (keep continuity)" in llm.user_prompt
    assert "a cat learns to fly" in llm.user_prompt
    assert "the cat jumps off the fence" in llm.user_prompt


async def test_generate_scene_omits_story_block_when_absent():
    from app.agents.scene_agent import generate_scene

    llm = CapturingLLM(SceneSpec(scene_id="s1", title="t", summary="sum", duration=5))
    await generate_scene(scene_id="s1", title="t", summary="sum", suggested_duration=5, client=llm)
    assert "Overall story and sibling scenes" not in llm.user_prompt


async def test_generate_shots_includes_story_block():
    from app.agents.shot_agent import generate_shots

    scene = SceneSpec(scene_id="s1", title="t", summary="sum", duration=5)
    llm = CapturingLLM(ShotList(scene_id="s1"))
    await generate_shots(scene=scene, story=STORY, client=llm)
    assert "Overall story and sibling scenes (keep continuity)" in llm.user_prompt
    assert "Sky Cat" in llm.user_prompt


async def test_generate_shots_omits_story_block_when_absent():
    from app.agents.shot_agent import generate_shots

    scene = SceneSpec(scene_id="s1", title="t", summary="sum", duration=5)
    llm = CapturingLLM(ShotList(scene_id="s1"))
    await generate_shots(scene=scene, client=llm)
    assert "Overall story and sibling scenes" not in llm.user_prompt


def test_prompts_carry_continuity_rule():
    from app.llm.prompts import PROMPTS

    for agent in ("shot_agent", "scene_agent"):
        assert "continuity with the overall story" in PROMPTS[agent]


def test_prompts_carry_at_mention_rule():
    from app.llm.prompts import PROMPTS

    for agent in ("shot_agent", "scene_agent"):
        assert "@Name" in PROMPTS[agent]
        assert "auto-linked" in PROMPTS[agent]
