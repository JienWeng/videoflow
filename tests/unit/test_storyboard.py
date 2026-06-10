"""Unit tests for the 分镜图 (storyboard contact-sheet) service."""

from __future__ import annotations

import pytest

from app.services.storyboard_service import build_storyboard_prompt, pick_grid


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
