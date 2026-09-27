"""Unit tests for prompt-agent reference collection and spec enforcement."""

from __future__ import annotations

from app.agents.prompt_agent import (
    NO_CLONE_NEGATIVE,
    NO_TEXT_NEGATIVE,
    cap_references,
    collect_named_references,
    enforce_render_defaults,
    voice_line,
)
from app.llm.prompts import PROMPTS
from app.schemas import CharacterBible, ReferenceImage, RenderSpec, StoryboardShot


def bible(
    name: str, asset_ids: list[str], voice_rules: list[str] | None = None
) -> CharacterBible:
    return CharacterBible(
        character_id=f"char_{name.lower().replace(' ', '_')}",
        name=name,
        appearance="",
        personality="",
        voice_rules=voice_rules or [],
        reference_asset_ids=asset_ids,
    )


class TestVoiceLine:
    def test_rules_joined_per_character(self):
        line = voice_line(
            [
                bible("乐乐", [], ["cheerful bright child's voice", "speaks slowly"]),
                bible("天天", [], ["low calm voice"]),
            ]
        )
        assert line == (
            "Voices: @乐乐 — cheerful bright child's voice, speaks slowly; "
            "@天天 — low calm voice"
        )

    def test_character_without_rules_is_skipped(self):
        line = voice_line([bible("Grace", [], ["warm voice"]), bible("Alan", [])])
        assert line == "Voices: @Grace — warm voice"

    def test_sample_dialogue_is_included(self):
        character = CharacterBible(
            character_id="char_maya",
            name="Maya",
            appearance="",
            personality="curious",
            sample_dialogue="What is that?",
        )
        assert voice_line([character]) == (
            "Voices: @Maya; sample dialogue: 「What is that?」"
        )

    def test_empty_when_nobody_has_rules(self):
        assert voice_line([bible("Grace", []), bible("Alan", [])]) == ""
        assert voice_line([]) == ""


class TestCollectNamedReferences:
    def test_caller_refs_come_first_verbatim(self):
        refs = collect_named_references(
            named_references=[{"name": "Kling Lipstick", "asset_id": "asset_a"}],
            character_bibles=[],
            shot_asset_ids=[],
            asset_names={},
        )
        assert refs == [{"name": "Kling Lipstick", "asset_id": "asset_a"}]

    def test_character_gets_exactly_one_reference_image(self):
        # CONTRACT CHANGE: previously every sheet was added ("Shirt Boy 2" for
        # extras), but Kling treats two named images of the same person as two
        # distinct people and renders clones. Only the FIRST sheet is sent now.
        refs = collect_named_references(
            named_references=[],
            character_bibles=[bible("Shirt Boy", ["asset_c1", "asset_c2"])],
            shot_asset_ids=[],
            asset_names={},
        )
        assert refs == [{"name": "Shirt Boy", "asset_id": "asset_c1"}]

    def test_shot_asset_named_like_a_character_is_skipped_not_uniquified(self):
        # A shot asset that is just another photo of a cast character must NOT
        # become "乐乐 2" — that names a second person and clones the character.
        refs = collect_named_references(
            named_references=[],
            character_bibles=[bible("乐乐", ["asset_c1"])],
            shot_asset_ids=["asset_extra_photo"],
            asset_names={"asset_extra_photo": "乐乐"},
        )
        assert refs == [{"name": "乐乐", "asset_id": "asset_c1"}]
        assert all("乐乐 2" != r["name"] for r in refs)

    def test_caller_ref_then_character_extra_photo_is_skipped(self):
        # Caller already supplied @Grace; the bible's sheet for Grace would be
        # a second image of the same person — skip it, don't emit "Grace 2".
        refs = collect_named_references(
            named_references=[{"name": "Grace", "asset_id": "asset_a"}],
            character_bibles=[bible("Grace", ["asset_b"])],
            shot_asset_ids=[],
            asset_names={},
        )
        assert refs == [{"name": "Grace", "asset_id": "asset_a"}]

    def test_shot_assets_are_added_by_asset_name(self):
        refs = collect_named_references(
            named_references=[],
            character_bibles=[],
            shot_asset_ids=["asset_bg", "asset_prop"],
            asset_names={"asset_bg": "Meadow", "asset_prop": "Red Kite"},
        )
        assert refs == [
            {"name": "Meadow", "asset_id": "asset_bg"},
            {"name": "Red Kite", "asset_id": "asset_prop"},
        ]

    def test_unnamed_shot_asset_falls_back_to_asset_id(self):
        refs = collect_named_references(
            named_references=[],
            character_bibles=[],
            shot_asset_ids=["asset_x"],
            asset_names={},
        )
        assert refs == [{"name": "asset_x", "asset_id": "asset_x"}]

    def test_duplicate_asset_ids_are_deduped_first_name_wins(self):
        refs = collect_named_references(
            named_references=[{"name": "Hero", "asset_id": "asset_1"}],
            character_bibles=[bible("Hero", ["asset_1"])],
            shot_asset_ids=["asset_1"],
            asset_names={"asset_1": "Hero Pic"},
        )
        assert refs == [{"name": "Hero", "asset_id": "asset_1"}]

    def test_clashing_non_character_names_get_unique_suffixes(self):
        # Two genuinely different PROPS sharing a name are still uniquified —
        # the skip rule applies only to character names (same-person photos).
        refs = collect_named_references(
            named_references=[{"name": "Image", "asset_id": "asset_1"}],
            character_bibles=[],
            shot_asset_ids=["asset_2"],
            asset_names={"asset_2": "Image"},
        )
        names = [r["name"] for r in refs]
        assert len(set(names)) == 2
        assert names[0] == "Image"
        assert names[1] == "Image 2"

    def test_all_sources_combined_in_order(self):
        refs = collect_named_references(
            named_references=[{"name": "Lipstick", "asset_id": "a"}],
            character_bibles=[bible("Grace", ["b"])],
            shot_asset_ids=["c"],
            asset_names={"c": "Sofa"},
        )
        assert [r["asset_id"] for r in refs] == ["a", "b", "c"]


def _ref(name: str) -> dict:
    return {"name": name, "asset_id": f"asset_{name}"}


class TestCapReferences:
    """Priority capping for the live Kling limit (ret:1201 above 7 images)."""

    def test_under_limit_passes_through_unchanged(self):
        groups = [[_ref("乐乐"), _ref("天天")], [_ref("分镜图")], [_ref("上一场景")]]
        assert cap_references(groups, 7) == [
            _ref("乐乐"), _ref("天天"), _ref("分镜图"), _ref("上一场景"),
        ]

    def test_exactly_at_limit_keeps_everything(self):
        groups = [[_ref(f"c{i}") for i in range(5)], [_ref("分镜图"), _ref("上一场景")]]
        assert len(cap_references(groups, 7)) == 7

    def test_over_limit_drops_props_first_keeps_high_priority_groups(self):
        chars = [_ref("乐乐"), _ref("天天")]
        storyboard = [_ref("分镜图")]
        anchor = [_ref("上一场景")]
        props = [_ref(f"prop{i}") for i in range(6)]
        capped = cap_references([chars, storyboard, anchor, props], 7)
        assert capped == chars + storyboard + anchor + props[:3]

    def test_order_preserved_within_groups(self):
        props = [_ref("a"), _ref("b"), _ref("c")]
        capped = cap_references([[_ref("char")], props], 3)
        assert capped == [_ref("char"), _ref("a"), _ref("b")]

    def test_storyboard_dropped_when_characters_alone_fill_the_limit(self):
        chars = [_ref(f"char{i}") for i in range(7)]
        capped = cap_references([chars, [_ref("分镜图")], [_ref("上一场景")]], 7)
        assert capped == chars

    def test_dropped_names_are_logged(self, caplog):
        with caplog.at_level("WARNING", logger="app.agents.prompt_agent"):
            cap_references([[_ref("乐乐")], [_ref("prop1"), _ref("prop2")]], 2)
        assert "prop2" in caplog.text
        assert "乐乐" not in caplog.text

    def test_no_warning_when_under_limit(self, caplog):
        with caplog.at_level("WARNING", logger="app.agents.prompt_agent"):
            cap_references([[_ref("乐乐")]], 7)
        assert caplog.text == ""

    def test_empty_groups_are_fine(self):
        assert cap_references([[], [_ref("a")], []], 7) == [_ref("a")]
        assert cap_references([], 7) == []


class FakeLLM:
    """Returns a canned RenderSpec the way a drifting model might: voice off,
    single-shot, and half the references dropped."""

    def __init__(self, spec: RenderSpec):
        self.spec = spec
        self.user_prompt: str | None = None

    async def generate(self, *, agent, response_model, user_prompt, context=None, images=None):
        assert response_model is RenderSpec
        self.user_prompt = user_prompt
        return self.spec.model_copy(deep=True)


class TestBuildRenderSpec:
    async def test_collects_all_references_and_enforces_defaults(self):
        from app.agents.prompt_agent import build_render_spec
        from app.schemas import ShotSpec

        drifted = RenderSpec(
            scene_id="wrong",
            duration=5,
            prompt="@Grace waves",
            reference_images=[ReferenceImage(name="Grace", asset_id="char_img")],
            sound=False,
            keep_original_sound=False,
        )
        llm = FakeLLM(drifted)
        shot = ShotSpec(
            shot_id="sh1",
            duration=5,
            prompt="Grace waves at the meadow",
            camera="mid-shot",
            movement="static",
            asset_ids=["bg_img"],
        )
        spec = await build_render_spec(
            scene_id="s1",
            scene_summary="summary",
            shot=shot,
            character_bibles=[bible("Grace", ["char_img"])],
            asset_names={"bg_img": "Meadow"},
            client=llm,
        )
        # Caller-controlled fields forced back.
        assert spec.scene_id == "s1"
        assert spec.shot_id == "sh1"
        # Character image + shot asset both reach reference_images.
        assert {(r.name, r.asset_id) for r in spec.reference_images} == {
            ("Grace", "char_img"),
            ("Meadow", "bg_img"),
        }
        # Voice + multi-shot enforced.
        assert spec.sound is True and spec.keep_original_sound is True
        assert spec.multi_shot is True and spec.shot_type == "intelligence"
        # The LLM was shown both named references.
        assert "Meadow" in llm.user_prompt and "bg_img" in llm.user_prompt

    async def test_story_block_included_when_passed(self):
        from app.agents.prompt_agent import build_render_spec
        from app.schemas import ShotSpec

        llm = FakeLLM(RenderSpec(scene_id="s1", duration=5, prompt="p"))
        shot = ShotSpec(shot_id="sh1", duration=5, prompt="Grace waves")
        story = {
            "story": {"idea": "a cat learns to fly", "title": "Sky Cat", "summary": "x"},
            "other_scenes": [{"title": "Takeoff", "summary": "the cat jumps off the fence"}],
        }
        await build_render_spec(
            scene_id="s1", scene_summary="sum", shot=shot, story=story, client=llm
        )
        assert "Overall story and sibling scenes (keep continuity)" in llm.user_prompt
        assert "a cat learns to fly" in llm.user_prompt
        assert "the cat jumps off the fence" in llm.user_prompt

    async def test_story_block_omitted_when_absent(self):
        from app.agents.prompt_agent import build_render_spec
        from app.schemas import ShotSpec

        llm = FakeLLM(RenderSpec(scene_id="s1", duration=5, prompt="p"))
        shot = ShotSpec(shot_id="sh1", duration=5, prompt="Grace waves")
        await build_render_spec(scene_id="s1", scene_summary="sum", shot=shot, client=llm)
        assert "Overall story and sibling scenes" not in llm.user_prompt


class TestEnforceRenderDefaults:
    def spec(self, **overrides) -> RenderSpec:
        base = dict(
            scene_id="s1",
            shot_id="sh1",
            duration=5,
            prompt="@Grace waves",
            reference_images=[ReferenceImage(name="Grace", asset_id="a")],
        )
        base.update(overrides)
        return RenderSpec(**base)

    def test_sound_forced_on(self):
        spec = self.spec(sound=False, keep_original_sound=False)
        enforce_render_defaults(spec, named_references=[])
        assert spec.sound is True
        assert spec.keep_original_sound is True

    def test_multi_shot_forced_to_intelligence_when_llm_skipped_it(self):
        spec = self.spec()
        enforce_render_defaults(spec, named_references=[])
        assert spec.multi_shot is True
        assert spec.shot_type == "intelligence"

    def test_customize_storyboard_left_untouched(self):
        spec = self.spec(
            multi_shot=True,
            shot_type="customize",
            multi_prompt=[
                StoryboardShot(prompt="beat one", duration=3),
                StoryboardShot(prompt="beat two", duration=2),
            ],
        )
        enforce_render_defaults(spec, named_references=[])
        assert spec.shot_type == "customize"
        assert len(spec.multi_prompt) == 2

    def test_dropped_named_references_are_restored(self):
        spec = self.spec()  # LLM echoed only Grace
        enforce_render_defaults(
            spec,
            named_references=[
                {"name": "Grace", "asset_id": "a"},
                {"name": "Sofa", "asset_id": "b"},
            ],
        )
        assert [(r.name, r.asset_id) for r in spec.reference_images] == [
            ("Grace", "a"),
            ("Sofa", "b"),
        ]

    def test_restored_references_capped_at_live_limit_characters_first(self):
        """8 refs (2 characters + 6 shot assets) -> capped to 7, both
        characters kept, the LAST shot asset dropped (props drop first)."""
        spec = self.spec(reference_images=[])
        bibles = [bible("Grace", ["char_a"]), bible("Alan", ["char_b"])]
        refs = (
            [{"name": "Grace", "asset_id": "char_a"},
             {"name": "Alan", "asset_id": "char_b"}]
            + [{"name": f"Prop {i}", "asset_id": f"prop_{i}"} for i in range(6)]
        )
        enforce_render_defaults(spec, named_references=refs, character_bibles=bibles)
        assert len(spec.reference_images) == 7
        names = [r.name for r in spec.reference_images]
        # Characters first, then shot assets in order, last prop dropped.
        assert names == ["Grace", "Alan"] + [f"Prop {i}" for i in range(5)]

    def test_no_cap_when_within_live_limit(self):
        spec = self.spec()
        refs = [{"name": "Grace", "asset_id": "a"},
                {"name": "Sofa", "asset_id": "b"}]
        enforce_render_defaults(spec, named_references=refs)
        assert len(spec.reference_images) == 2

    def test_no_text_negative_appended_when_missing(self):
        spec = self.spec()  # prompt has no subtitle negative
        enforce_render_defaults(spec, named_references=[])
        assert NO_TEXT_NEGATIVE in spec.prompt
        assert "no subtitles" in spec.prompt.lower()

    def test_no_text_negative_not_double_appended(self):
        spec = self.spec(
            prompt="@Grace waves. Negative: NO SUBTITLES, no on-screen text."
        )
        enforce_render_defaults(spec, named_references=[])
        assert spec.prompt.lower().count("no subtitles") == 1
        assert NO_TEXT_NEGATIVE not in spec.prompt

    def test_no_clone_negative_appended_when_missing(self):
        spec = self.spec()
        enforce_render_defaults(spec, named_references=[])
        assert NO_CLONE_NEGATIVE in spec.prompt

    def test_no_clone_negative_appended_only_once_on_rerun(self):
        spec = self.spec()
        enforce_render_defaults(spec, named_references=[])
        enforce_render_defaults(spec, named_references=[])
        assert spec.prompt.lower().count("no clones") == 1

    def test_no_clone_negative_respects_existing_wording(self):
        spec = self.spec(prompt="@Grace waves. Negative: NO CLONES or twins.")
        enforce_render_defaults(spec, named_references=[])
        assert spec.prompt.lower().count("no clones") == 1
        assert NO_CLONE_NEGATIVE not in spec.prompt

    def test_voice_line_appended_when_cast_has_voice_rules(self):
        spec = self.spec()
        enforce_render_defaults(
            spec,
            named_references=[],
            character_bibles=[bible("Grace", ["a"], ["warm gentle voice"])],
        )
        assert "Voices: @Grace — warm gentle voice" in spec.prompt
        # Voice direction comes BEFORE the negative guidance.
        assert spec.prompt.index("Voices:") < spec.prompt.index("no subtitles")

    def test_voice_line_idempotent_on_rerun(self):
        spec = self.spec()
        bibles = [bible("Grace", ["a"], ["warm gentle voice"])]
        enforce_render_defaults(spec, named_references=[], character_bibles=bibles)
        enforce_render_defaults(spec, named_references=[], character_bibles=bibles)
        assert spec.prompt.count("Voices:") == 1

    def test_voice_line_skipped_when_no_rules(self):
        spec = self.spec()
        enforce_render_defaults(
            spec, named_references=[], character_bibles=[bible("Grace", ["a"])]
        )
        assert "Voices:" not in spec.prompt

    def test_voice_line_skipped_when_already_present(self):
        spec = self.spec(prompt="@Grace waves. Voices: @Grace — squeaky robot voice.")
        enforce_render_defaults(
            spec,
            named_references=[],
            character_bibles=[bible("Grace", ["a"], ["warm gentle voice"])],
        )
        assert spec.prompt.count("Voices:") == 1
        assert "warm gentle voice" not in spec.prompt


class TestPromptRules:
    """The planning prompts must teach the two production rules: captions are
    post-production (dialogue in 「」), and one scene renders ONE video."""

    def test_caption_rule_in_planning_prompts(self):
        for agent in ("script_agent", "scene_agent", "shot_agent", "prompt_agent"):
            assert "post-production" in PROMPTS[agent], agent
            assert "「」" in PROMPTS[agent], agent

    def test_one_video_rule_in_scene_and_shot_prompts(self):
        assert "ONE multi-shot video" in PROMPTS["scene_agent"]
        assert "ONE multi-shot video" in PROMPTS["shot_agent"]
        assert "ONE RenderSpec for ONE video" in PROMPTS["prompt_agent"]

    def test_every_shot_speaks_rule_in_shot_prompt(self):
        assert "EVERY shot MUST include" in PROMPTS["shot_agent"]

    def test_every_multi_prompt_entry_speaks_rule_in_prompt_agent(self):
        assert "EVERY multi_prompt entry" in PROMPTS["prompt_agent"]

    def test_no_clone_rule_in_prompt_agent_negative_guidance(self):
        assert "no duplicated characters" in PROMPTS["prompt_agent"]
        assert "no clones or twins" in PROMPTS["prompt_agent"]

    def test_voice_consistency_rule_in_prompt_agent(self):
        assert "ONE consistent voice" in PROMPTS["prompt_agent"]
        assert "voice_rules" in PROMPTS["prompt_agent"]
        assert "Never change a character's voice between shots" in PROMPTS["prompt_agent"]

    def test_character_memory_demands_reproducible_voice_rules(self):
        assert "voice_rules MUST describe a concrete, reproducible voice" in (
            PROMPTS["character_memory"]
        )
