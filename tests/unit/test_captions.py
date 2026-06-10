"""Unit tests for auto-caption ASS subtitle generation."""

from __future__ import annotations

import pytest

from app.services.caption_service import (
    STYLES,
    CaptionSegment,
    build_ass,
    format_ass_time,
)


class TestFormatAssTime:
    def test_zero(self):
        assert format_ass_time(0) == "0:00:00.00"

    def test_subsecond_rounding(self):
        assert format_ass_time(1.504) == "0:00:01.50"

    def test_minutes_and_hours(self):
        assert format_ass_time(75.2) == "0:01:15.20"
        assert format_ass_time(3661.0) == "1:01:01.00"


class TestBuildAss:
    def segments(self):
        return [
            CaptionSegment(start=0.0, end=2.5, text="我是乐乐，乐乐是我！"),
            CaptionSegment(start=3.0, end=5.5, text="我是天天，天天是我！"),
        ]

    def test_contains_styles_and_dialogue(self):
        ass = build_ass(self.segments(), style="kids", play_res=(1080, 1920))
        assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
        # The kids preset is one of the named styles, declared in V4+ format.
        assert "[V4+ Styles]" in ass
        assert "Noto Sans CJK SC" in ass
        assert "Dialogue: 0,0:00:00.00,0:00:02.50,Caption,,0,0,0,,我是乐乐，乐乐是我！" in ass
        assert "Dialogue: 0,0:00:03.00,0:00:05.50,Caption,,0,0,0,,我是天天，天天是我！" in ass

    def test_all_presets_are_valid(self):
        for name in STYLES:
            ass = build_ass(self.segments(), style=name)
            assert "[Events]" in ass

    def test_unknown_style_rejected(self):
        with pytest.raises(ValueError):
            build_ass(self.segments(), style="nope")

    def test_text_newlines_become_ass_linebreaks(self):
        ass = build_ass([CaptionSegment(start=0, end=1, text="a\nb")], style="clean")
        assert ",,a\\Nb" in ass
