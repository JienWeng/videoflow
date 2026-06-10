"""Unit tests for prompt-agent reference collection and spec enforcement."""

from __future__ import annotations

from app.agents.prompt_agent import collect_named_references, enforce_render_defaults
from app.schemas import CharacterBible, ReferenceImage, RenderSpec, StoryboardShot


def bible(name: str, asset_ids: list[str]) -> CharacterBible:
    return CharacterBible(
        character_id=f"char_{name.lower().replace(' ', '_')}",
        name=name,
        appearance="",
        personality="",
        reference_asset_ids=asset_ids,
    )


class TestCollectNamedReferences:
    def test_caller_refs_come_first_verbatim(self):
        refs = collect_named_references(
            named_references=[{"name": "Kling Lipstick", "asset_id": "asset_a"}],
            character_bibles=[],
            shot_asset_ids=[],
            asset_names={},
        )
        assert refs == [{"name": "Kling Lipstick", "asset_id": "asset_a"}]

    def test_character_reference_images_are_added_by_character_name(self):
        refs = collect_named_references(
            named_references=[],
            character_bibles=[bible("Shirt Boy", ["asset_c1", "asset_c2"])],
            shot_asset_ids=[],
            asset_names={},
        )
        # First image is @Shirt Boy; extras get numeric suffixes like Kling's @image1.
        assert refs == [
            {"name": "Shirt Boy", "asset_id": "asset_c1"},
            {"name": "Shirt Boy 2", "asset_id": "asset_c2"},
        ]

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

    def test_clashing_names_get_unique_suffixes(self):
        refs = collect_named_references(
            named_references=[{"name": "Image", "asset_id": "asset_1"}],
            character_bibles=[],
            shot_asset_ids=["asset_2"],
            asset_names={"asset_2": "Image"},
        )
        names = [r["name"] for r in refs]
        assert len(set(names)) == 2
        assert names[0] == "Image"

    def test_all_sources_combined_in_order(self):
        refs = collect_named_references(
            named_references=[{"name": "Lipstick", "asset_id": "a"}],
            character_bibles=[bible("Grace", ["b"])],
            shot_asset_ids=["c"],
            asset_names={"c": "Sofa"},
        )
        assert [r["asset_id"] for r in refs] == ["a", "b", "c"]


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
