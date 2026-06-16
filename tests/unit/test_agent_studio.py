"""Unit tests for Agent Studio: editable prompts, tuning, and context gating."""

from __future__ import annotations

import pytest

from app.agents.base import gated_block
from app.llm import skills
from app.llm.prompts import PROMPTS, extract_placeholders
from app.llm.structured_client import _format


@pytest.fixture(autouse=True)
def _clean_overrides():
    skills.clear_overrides()
    yield
    skills.clear_overrides()


# ----------------------------------------------------------- placeholders
def test_extract_placeholders_finds_real_fields():
    assert extract_placeholders("hello {name}, you are {role}") == {"name", "role"}


def test_extract_placeholders_ignores_escaped_braces():
    # `{{x}}` is a literal `{x}` after formatting, not a placeholder.
    assert extract_placeholders("echo {{name, asset_id}} verbatim") == set()


def test_default_prompts_have_no_placeholders():
    # Every default prompt is static rule text (context flows via the user prompt),
    # so the allowed-placeholder set is empty for all agents.
    for agent, template in PROMPTS.items():
        assert extract_placeholders(template) == set(), agent


# ------------------------------------------------------------- mirror merge
def test_set_record_overrides_system_prompt():
    base = skills.get_skill("script_agent")
    skills.set_record("script_agent", system_prompt="Write only haiku.")
    eff = skills.get_effective_skill("script_agent")
    assert eff.system_prompt == "Write only haiku."
    # untouched fields keep the base values.
    assert eff.provider == base.provider
    assert eff.temperature == base.temperature


def test_set_record_overrides_temperature_and_retries():
    skills.set_record("scene_agent", temperature=0.1, max_retries=5)
    eff = skills.get_effective_skill("scene_agent")
    assert eff.temperature == 0.1
    assert eff.max_retries == 5


def test_set_record_none_fields_keep_base():
    base = skills.get_skill("shot_agent")
    skills.set_record("shot_agent", provider="atlas", model="glm-5v")
    eff = skills.get_effective_skill("shot_agent")
    assert eff.provider == "atlas" and eff.model == "glm-5v"
    assert eff.system_prompt == base.system_prompt
    assert eff.temperature == base.temperature


# --------------------------------------------------------- context excludes
def test_context_excludes_defaults_empty():
    assert skills.context_excludes("scene_agent") == set()


def test_context_excludes_reflects_record():
    skills.set_record("scene_agent", context_excludes=["style", "story"])
    assert skills.context_excludes("scene_agent") == {"style", "story"}


def test_every_agent_has_context_sources_registered():
    for agent in skills.SKILLS:
        assert agent in skills.AGENT_CONTEXT_SOURCES, agent


# ------------------------------------------------------------- gated_block
def test_gated_block_keeps_block_by_default():
    out = gated_block("scene_agent", "style", "Project style guide", {"palette": "warm"})
    assert out and out[0].startswith("### Project style guide")


def test_gated_block_drops_when_excluded():
    skills.set_record("scene_agent", context_excludes=["style"])
    out = gated_block("scene_agent", "style", "Project style guide", {"palette": "warm"})
    assert out == []


def test_gated_block_drops_empty_value():
    assert gated_block("scene_agent", "story", "Overall story", None) == []
    assert gated_block("scene_agent", "story", "Overall story", []) == []
    assert gated_block("scene_agent", "story", "Overall story", {}) == []


# ---------------------------------------------------------- _format safety
def test_format_does_not_raise_on_malformed_braces():
    # A user-entered prompt with a lone brace must never crash an agent call.
    assert _format("a lone { brace", {"x": 1}) == "a lone { brace"


def test_format_returns_template_on_unknown_placeholder():
    assert _format("hi {missing}", {"x": 1}) == "hi {missing}"


# ------------------------------------------------ per-agent context gating
from app.schemas import CharacterBible, SceneSpec, ShotList, ShotSpec  # noqa: E402


class CapturingLLM:
    def __init__(self, result):
        self.result = result
        self.user_prompt: str | None = None
        self.images = None

    async def generate(self, *, agent, response_model, user_prompt, context=None, images=None):
        self.user_prompt = user_prompt
        self.images = images
        return self.result


STYLE = {"style_prompt": "flat pastel cartoon", "palette": "warm"}
STORY = {"story": {"idea": "a cat learns to fly"}}


async def test_shot_agent_style_block_dropped_when_excluded():
    from app.agents.shot_agent import generate_shots

    scene = SceneSpec(scene_id="s1", title="t", summary="sum", duration=5)
    # baseline: present
    llm = CapturingLLM(ShotList(scene_id="s1"))
    await generate_shots(scene=scene, style=STYLE, client=llm)
    assert "Project style guide" in llm.user_prompt
    # excluded: gone
    skills.set_record("shot_agent", context_excludes=["style"])
    llm = CapturingLLM(ShotList(scene_id="s1"))
    await generate_shots(scene=scene, style=STYLE, client=llm)
    assert "Project style guide" not in llm.user_prompt
    assert "flat pastel cartoon" not in llm.user_prompt


async def test_scene_agent_story_block_dropped_when_excluded():
    from app.agents.scene_agent import generate_scene

    skills.set_record("scene_agent", context_excludes=["story"])
    llm = CapturingLLM(SceneSpec(scene_id="s1", title="t", summary="sum", duration=5))
    await generate_scene(
        scene_id="s1", title="t", summary="sum", suggested_duration=5,
        story=STORY, client=llm,
    )
    assert "Overall story" not in llm.user_prompt


async def test_script_agent_characters_block_dropped_when_excluded():
    from app.agents.script_agent import generate_script
    from app.schemas import ScriptDraft

    skills.set_record("script_agent", context_excludes=["characters"])
    llm = CapturingLLM(ScriptDraft(title="t", summary="s"))
    await generate_script(idea="x", characters=[{"name": "Milo"}], client=llm)
    assert "Existing characters" not in llm.user_prompt


async def test_prompt_agent_style_block_dropped_when_excluded():
    from app.agents.prompt_agent import build_render_spec
    from app.schemas import RenderSpec

    skills.set_record("prompt_agent", context_excludes=["style"])
    shot = ShotSpec(shot_id="sh1", shot_order=1, prompt="p", duration=5)
    llm = CapturingLLM(RenderSpec(scene_id="s1", shot_id="sh1", prompt="p", duration=5))
    await build_render_spec(
        scene_id="s1", scene_summary="sum", shot=shot, style=STYLE, client=llm,
    )
    assert "Project style guide" not in llm.user_prompt


async def test_intent_agent_history_block_dropped_when_excluded():
    from app.agents.intent_agent import classify_intent
    from app.schemas import Intent

    skills.set_record("intent_agent", context_excludes=["history"])
    llm = CapturingLLM(Intent(action="unknown", reply="hi", confidence=0.5))
    await classify_intent(
        message="hello", scenes=[], characters=[],
        history=[{"role": "user", "content": "earlier"}], client=llm,
    )
    assert "Conversation so far" not in llm.user_prompt


async def test_qa_agent_reference_images_dropped_when_excluded():
    from app.agents.qa_agent import review_output
    from app.schemas import QAResult

    skills.set_record("qa_agent", context_excludes=["reference_images"])
    llm = CapturingLLM(
        QAResult(score=8, passed=True, issues=[], recommendation="accept")
    )
    await review_output(
        requirements="r", output_description="d",
        frames=["/f1.jpg"], reference_images=["/ref1.jpg"], client=llm,
    )
    assert llm.images == ["/f1.jpg"]  # reference dropped, frames kept
