"""Style guide enforcement: deterministic prompt suffix + agent context blocks."""

from __future__ import annotations

from app.models import StyleGuide
from app.schemas import RenderSpec, SceneSpec, ShotList, ShotSpec
from app.services.style_service import apply_style, style_context, style_suffix


def guide(**kw) -> StyleGuide:
    return StyleGuide(**kw)


class TestStyleSuffix:
    def test_none_style_is_empty(self):
        assert style_suffix(None) == ""

    def test_empty_guide_is_empty(self):
        assert style_suffix(guide()) == ""

    def test_combines_prompt_palette_lighting(self):
        s = guide(style_prompt="3D cartoon", palette="soft pastel", lighting="warm sun")
        assert style_suffix(s) == ". Style: 3D cartoon; palette: soft pastel; lighting: warm sun"

    def test_skips_blank_fields(self):
        assert style_suffix(guide(palette="soft pastel")) == ". Style: palette: soft pastel"


class TestApplyStyle:
    def test_no_style_unchanged(self):
        assert apply_style("a red cup", None) == "a red cup"
        assert apply_style("a red cup", guide()) == "a red cup"

    def test_suffix_appended_once(self):
        s = guide(style_prompt="3D cartoon, soft pastel")
        out = apply_style("a red cup.", s)
        assert out == "a red cup. Style: 3D cartoon, soft pastel"
        assert out.count("3D cartoon, soft pastel") == 1

    def test_idempotent(self):
        s = guide(style_prompt="3D cartoon", lighting="warm sun")
        once = apply_style("a red cup", s)
        assert apply_style(once, s) == once


class TestStyleContext:
    def test_none(self):
        assert style_context(None) is None
        assert style_context(guide()) is None

    def test_only_non_empty_fields(self):
        s = guide(style_prompt="3D cartoon", audience="children 2-6")
        assert style_context(s) == {"style_prompt": "3D cartoon", "audience": "children 2-6"}


# ── agents receive the style as a context block ──────────────────────────────

STYLE = {"style_prompt": "3D cartoon", "palette": "soft pastel", "tone": "playful"}


class CapturingLLM:
    def __init__(self, result):
        self.result = result
        self.user_prompt: str | None = None

    async def generate(self, *, agent, response_model, user_prompt, context=None, images=None):
        self.user_prompt = user_prompt
        return self.result


async def test_generate_scene_includes_style_block():
    from app.agents.scene_agent import generate_scene

    spec = SceneSpec(scene_id="s1", title="t", summary="sum", duration=5)
    llm = CapturingLLM(spec)
    await generate_scene(
        scene_id="s1", title="t", summary="sum", suggested_duration=5,
        style=STYLE, client=llm,
    )
    assert "Project style guide" in llm.user_prompt
    assert "3D cartoon" in llm.user_prompt
    assert "playful" in llm.user_prompt


async def test_generate_scene_without_style_omits_block():
    from app.agents.scene_agent import generate_scene

    llm = CapturingLLM(SceneSpec(scene_id="s1", title="t", summary="sum", duration=5))
    await generate_scene(scene_id="s1", title="t", summary="sum", suggested_duration=5, client=llm)
    assert "Project style guide" not in llm.user_prompt


async def test_generate_shots_includes_style_block():
    from app.agents.shot_agent import generate_shots

    scene = SceneSpec(scene_id="s1", title="t", summary="sum", duration=5)
    llm = CapturingLLM(ShotList(scene_id="s1"))
    await generate_shots(scene=scene, style=STYLE, client=llm)
    assert "Project style guide" in llm.user_prompt
    assert "soft pastel" in llm.user_prompt


async def test_generate_shots_without_style_omits_block():
    from app.agents.shot_agent import generate_shots

    scene = SceneSpec(scene_id="s1", title="t", summary="sum", duration=5)
    llm = CapturingLLM(ShotList(scene_id="s1"))
    await generate_shots(scene=scene, client=llm)
    assert "Project style guide" not in llm.user_prompt


async def test_build_render_spec_includes_style_block():
    from app.agents.prompt_agent import build_render_spec

    shot = ShotSpec(shot_id="sh1", duration=5, prompt="Grace waves")
    llm = CapturingLLM(RenderSpec(scene_id="s1", shot_id="sh1", duration=5, prompt="p"))
    await build_render_spec(
        scene_id="s1", scene_summary="sum", shot=shot, style=STYLE, client=llm
    )
    assert "Project style guide" in llm.user_prompt
    assert "3D cartoon" in llm.user_prompt


async def test_plan_assets_includes_style_block():
    from app.agents.asset_planner import plan_assets
    from app.schemas import AssetPlan

    llm = CapturingLLM(AssetPlan())
    await plan_assets(
        scene_summary="s", scene_json={}, existing_assets=[], style=STYLE, client=llm
    )
    assert "Style guide" in llm.user_prompt
    assert "3D cartoon" in llm.user_prompt


async def test_plan_assets_without_style_omits_block():
    from app.agents.asset_planner import plan_assets
    from app.schemas import AssetPlan

    llm = CapturingLLM(AssetPlan())
    await plan_assets(scene_summary="s", scene_json={}, existing_assets=[], client=llm)
    assert "Style guide" not in llm.user_prompt


async def test_generate_script_includes_style_block():
    from app.agents.script_agent import generate_script
    from app.schemas import ScriptDraft

    llm = CapturingLLM(ScriptDraft(title="t", summary="s"))
    await generate_script(idea="a cat story", style=STYLE, client=llm)
    assert "Project style guide" in llm.user_prompt
    assert "3D cartoon" in llm.user_prompt
    assert "playful" in llm.user_prompt


async def test_generate_script_without_style_omits_block():
    from app.agents.script_agent import generate_script
    from app.schemas import ScriptDraft

    llm = CapturingLLM(ScriptDraft(title="t", summary="s"))
    await generate_script(idea="a cat story", client=llm)
    assert "Project style guide" not in llm.user_prompt


async def test_build_character_bible_includes_style_block():
    from app.agents.character_memory import build_character_bible
    from app.schemas import CharacterBible

    bible = CharacterBible(character_id="c1", name="Grace", appearance="a", personality="p")
    llm = CapturingLLM(bible)
    await build_character_bible(
        character_id="c1", name="Grace", notes="n", style=STYLE, client=llm
    )
    assert "Project style guide" in llm.user_prompt
    assert "soft pastel" in llm.user_prompt
    assert "sample_dialogue" in llm.user_prompt
    assert "one natural spoken line" in llm.user_prompt


async def test_build_character_bible_without_style_omits_block():
    from app.agents.character_memory import build_character_bible
    from app.schemas import CharacterBible

    bible = CharacterBible(character_id="c1", name="Grace", appearance="a", personality="p")
    llm = CapturingLLM(bible)
    await build_character_bible(character_id="c1", name="Grace", notes="n", client=llm)
    assert "Project style guide" not in llm.user_prompt
