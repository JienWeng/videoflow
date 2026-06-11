"""Unit tests for the 分镜图 (storyboard contact-sheet) service."""

from __future__ import annotations

import pytest

from app.services.storyboard_service import (
    build_storyboard_prompt,
    collect_prop_reference_ids,
    pick_grid,
)


class TestPickGrid:
    def test_minimum_grid_is_2x2(self):
        assert pick_grid(1) == 2
        assert pick_grid(4) == 2

    def test_grid_grows_to_fit_beats(self):
        assert pick_grid(5) == 3
        assert pick_grid(9) == 3
        assert pick_grid(10) == 4
        assert pick_grid(16) == 4

    def test_more_than_16_beats_rejected(self):
        with pytest.raises(ValueError):
            pick_grid(17)


class TestBuildStoryboardPrompt:
    def test_prompt_contains_grid_panels_characters_and_consistency_rules(self):
        prompt = build_storyboard_prompt(
            beats=["乐乐 waves hello", "天天 twirls", "咪咪 pounces", "all three cheer"],
            character_lines=[
                "乐乐: toddler boy, orange t-shirt, denim shorts",
                "天天: toddler girl, pink dress, black pigtails",
            ],
            setting="sunny kindergarten playroom",
            lighting="warm soft morning daylight",
        )
        # 4 beats -> 2x2 grid of numbered panels.
        assert "2x2" in prompt
        assert "Panel 1: 乐乐 waves hello" in prompt
        assert "Panel 4: all three cheer" in prompt
        # Character identity lines included for 上相一致.
        assert "orange t-shirt" in prompt and "pink dress" in prompt
        # 场景连贯 / 光线氛围 directives.
        assert "sunny kindergarten playroom" in prompt
        assert "warm soft morning daylight" in prompt
        assert "same characters" in prompt.lower()
        assert "no text" in prompt.lower()


class _FakeAsset:
    """Minimal stand-in for app.models.Asset for unit tests."""

    def __init__(self, id: str, type: str, file_path: str | None = None):
        self.id = id
        self.type = type
        self.file_path = file_path


class _FakeShot:
    def __init__(self, asset_ids: list[str]):
        self.asset_ids_json = asset_ids


class _FakeScene:
    def __init__(self, asset_ids: list[str]):
        self.asset_ids_json = asset_ids


class TestCollectPropReferenceIds:
    """Tests for the pure helper that gathers prop/asset ids for storyboard refs."""

    def _assets(self, specs: list[tuple[str, str, str | None]]) -> dict[str, _FakeAsset]:
        """Build an assets_by_id dict from (id, type, file_path) tuples."""
        return {id_: _FakeAsset(id_, type_, fp) for id_, type_, fp in specs}

    def test_prop_assets_included(self):
        """Prop assets with an image file_path are returned."""
        assets = self._assets([("prop_1", "prop", "/img/cup.png")])
        scene = _FakeScene(asset_ids=["prop_1"])
        result = collect_prop_reference_ids(
            scene=scene, shots=[], assets_by_id=assets, already_in=set()
        )
        assert result == ["prop_1"]

    def test_background_assets_included(self):
        """Background-type assets are included (not in the exclusion list)."""
        assets = self._assets([("bg_1", "background", "/img/bg.png")])
        scene = _FakeScene(asset_ids=["bg_1"])
        result = collect_prop_reference_ids(
            scene=scene, shots=[], assets_by_id=assets, already_in=set()
        )
        assert result == ["bg_1"]

    def test_video_assets_excluded(self):
        """Assets of type 'video' are never included."""
        assets = self._assets([("vid_1", "video", "/vid.mp4")])
        scene = _FakeScene(asset_ids=["vid_1"])
        result = collect_prop_reference_ids(
            scene=scene, shots=[], assets_by_id=assets, already_in=set()
        )
        assert result == []

    def test_storyboard_assets_excluded(self):
        """Assets of type 'storyboard' are never included."""
        assets = self._assets([("sb_1", "storyboard", "/img/sb.png")])
        scene = _FakeScene(asset_ids=["sb_1"])
        result = collect_prop_reference_ids(
            scene=scene, shots=[], assets_by_id=assets, already_in=set()
        )
        assert result == []

    def test_character_reference_assets_excluded(self):
        """Assets of type 'character_reference' are excluded (already in cast sheets)."""
        assets = self._assets([("cr_1", "character_reference", "/img/sheet.png")])
        scene = _FakeScene(asset_ids=["cr_1"])
        result = collect_prop_reference_ids(
            scene=scene, shots=[], assets_by_id=assets, already_in=set()
        )
        assert result == []

    def test_asset_without_file_path_excluded(self):
        """An asset with no file_path (unrendered) is skipped."""
        assets = self._assets([("prop_nf", "prop", None)])
        scene = _FakeScene(asset_ids=["prop_nf"])
        result = collect_prop_reference_ids(
            scene=scene, shots=[], assets_by_id=assets, already_in=set()
        )
        assert result == []

    def test_already_in_set_excludes_duplicates(self):
        """IDs already in `already_in` are never re-added."""
        assets = self._assets([("prop_1", "prop", "/img/cup.png")])
        scene = _FakeScene(asset_ids=["prop_1"])
        result = collect_prop_reference_ids(
            scene=scene, shots=[], assets_by_id=assets, already_in={"prop_1"}
        )
        assert result == []

    def test_shot_assets_included(self):
        """Assets referenced by individual shots are collected."""
        assets = self._assets([("prop_s", "prop", "/img/prop.png")])
        scene = _FakeScene(asset_ids=[])
        shot = _FakeShot(asset_ids=["prop_s"])
        result = collect_prop_reference_ids(
            scene=scene, shots=[shot], assets_by_id=assets, already_in=set()
        )
        assert result == ["prop_s"]

    def test_ordering_scene_then_shots_and_dedup(self):
        """Scene-level assets come before shot-level assets; duplicates collapsed."""
        assets = self._assets([
            ("prop_a", "prop", "/img/a.png"),
            ("prop_b", "prop", "/img/b.png"),
            ("prop_c", "prop", "/img/c.png"),
        ])
        scene = _FakeScene(asset_ids=["prop_a", "prop_b"])
        shot1 = _FakeShot(asset_ids=["prop_b", "prop_c"])  # prop_b already in scene
        result = collect_prop_reference_ids(
            scene=scene, shots=[shot1], assets_by_id=assets, already_in=set()
        )
        assert result == ["prop_a", "prop_b", "prop_c"]

    def test_cap_at_provider_limit(self):
        """Result is capped at 10 total (the provider image limit)."""
        assets = self._assets(
            [(f"prop_{i}", "prop", f"/img/{i}.png") for i in range(12)]
        )
        scene = _FakeScene(asset_ids=[f"prop_{i}" for i in range(12)])
        result = collect_prop_reference_ids(
            scene=scene, shots=[], assets_by_id=assets, already_in=set()
        )
        assert len(result) == 10

    def test_cap_respects_already_in_budget(self):
        """When already_in already uses 8 slots, only 2 prop slots remain."""
        assets = self._assets(
            [(f"prop_{i}", "prop", f"/img/{i}.png") for i in range(5)]
        )
        scene = _FakeScene(asset_ids=[f"prop_{i}" for i in range(5)])
        already_in = {f"style_{j}" for j in range(8)}
        result = collect_prop_reference_ids(
            scene=scene, shots=[], assets_by_id=assets, already_in=already_in
        )
        assert len(result) == 2

    def test_missing_asset_id_silently_skipped(self):
        """An asset_id not in assets_by_id is silently skipped (no error)."""
        assets = self._assets([("prop_1", "prop", "/img/cup.png")])
        scene = _FakeScene(asset_ids=["prop_1", "missing_id"])
        result = collect_prop_reference_ids(
            scene=scene, shots=[], assets_by_id=assets, already_in=set()
        )
        assert result == ["prop_1"]
