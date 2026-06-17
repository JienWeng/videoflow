"""Phase 2c: targeted RenderSpecPatch application (pure)."""

from __future__ import annotations

from app.schemas import ReferenceImage, RenderSpec, StoryboardShot
from app.schemas.render_patch_schema import (
    ReferencePatch, RenderSpecPatch, ShotPromptPatch,
)
from app.services.render_service import apply_render_patch


def _spec() -> RenderSpec:
    return RenderSpec(
        scene_id="s1",
        duration=10,
        aspect_ratio="9:16",
        prompt="base prompt",
        reference_images=[
            ReferenceImage(name="乐乐", asset_id="a1"),
            ReferenceImage(name="Red Cup", asset_id="a2"),
        ],
        multi_shot=True,
        shot_type="customize",
        multi_prompt=[
            StoryboardShot(prompt="shot one 「hi」", duration=5),
            StoryboardShot(prompt="shot two 「bye」", duration=5),
        ],
    )


def test_patch_replaces_single_shot_prompt():
    spec = _spec()
    out = apply_render_patch(spec, RenderSpecPatch(
        rationale="fix shot 2",
        shot_prompts=[ShotPromptPatch(index=2, prompt="shot two fixed 「bye」")],
    ))
    assert out.multi_prompt[0].prompt == "shot one 「hi」"      # untouched
    assert out.multi_prompt[1].prompt == "shot two fixed 「bye」"
    assert out.multi_prompt[1].duration == 5                    # duration kept


def test_patch_swaps_reference_asset_by_name():
    spec = _spec()
    out = apply_render_patch(spec, RenderSpecPatch(
        rationale="stronger sheet",
        references=[ReferencePatch(op="swap", name="乐乐", asset_id="a9")],
    ))
    ref = next(r for r in out.reference_images if r.name == "乐乐")
    assert ref.asset_id == "a9"


def test_patch_removes_reference():
    spec = _spec()
    out = apply_render_patch(spec, RenderSpecPatch(
        rationale="drop cup",
        references=[ReferencePatch(op="remove", name="Red Cup")],
    ))
    assert all(r.name != "Red Cup" for r in out.reference_images)


def test_patch_never_adds_unknown_reference_name():
    spec = _spec()
    out = apply_render_patch(spec, RenderSpecPatch(
        rationale="try to add",
        references=[ReferencePatch(op="swap", name="Ghost", asset_id="zz")],
    ))
    # 'Ghost' was not already present -> ignored (no clone risk).
    assert all(r.name != "Ghost" for r in out.reference_images)


def test_patch_replaces_main_prompt_and_ignores_bad_index():
    spec = _spec()
    out = apply_render_patch(spec, RenderSpecPatch(
        rationale="rewrite",
        main_prompt="new base",
        shot_prompts=[ShotPromptPatch(index=99, prompt="nope")],
    ))
    assert out.prompt == "new base"
    assert len(out.multi_prompt) == 2  # out-of-range index ignored, nothing added
