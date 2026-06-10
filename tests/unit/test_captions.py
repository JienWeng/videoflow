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


from app.services.caption_service import WHISPER_MODELS


def test_whisper_model_registry():
    assert WHISPER_MODELS == ["tiny", "base", "small", "medium", "large-v3"]


# ---------------------------------------------------------------------------
# Script-corrected captions
# ---------------------------------------------------------------------------

from app.services.caption_service import correct_segments, extract_script_lines


def test_extract_script_lines_from_spec():
    spec = {
        "prompt": "Wide shot: 乐乐 says 「我是乐乐 乐乐是我」 cheerfully",
        "multi_prompt": [
            {"prompt": '天天 waves and says 「我是天天 天天是我」', "duration": 3},
            {"prompt": "The kitten just meows", "duration": 2},
        ],
    }
    assert extract_script_lines(spec) == ["我是乐乐 乐乐是我", "我是天天 天天是我"]


def test_extract_script_lines_handles_missing():
    assert extract_script_lines(None) == []
    assert extract_script_lines({"prompt": "no quotes here"}) == []


def test_correct_segments_fixes_misheard_text_keeps_timing():
    segs = [
        CaptionSegment(start=0.0, end=1.5, text="我是乐乐乐乐是我"),   # close match (exact after norm)
        CaptionSegment(start=1.5, end=3.0, text="我是天天天是我"),     # misheard — closer to "我是天天 天天是我"
        CaptionSegment(start=3.0, end=4.0, text="喵"),               # no match -> kept
    ]
    lines = ["我是乐乐 乐乐是我", "我是天天 天天是我"]
    out = correct_segments(segs, lines)
    assert out[0].text == "我是乐乐 乐乐是我"
    assert out[1].text == "我是天天 天天是我"
    assert out[2].text == "喵"
    assert (out[0].start, out[0].end) == (0.0, 1.5)


def test_correct_segments_no_lines_is_noop():
    segs = [CaptionSegment(start=0, end=1, text="hello")]
    assert correct_segments(segs, []) == segs


def test_correct_segments_homophone_mishear_routes_by_order():
    """Monotonic alignment must route 田田 (homophone mishear of 天天) to the SECOND
    script line because the first segment already consumed the first line."""
    segs = [
        CaptionSegment(start=0.0, end=1.5, text="我是乐乐乐乐是我"),
        CaptionSegment(start=1.5, end=3.0, text="我是田田田田是我"),  # homophone mishear of 天天
    ]
    lines = ["我是乐乐 乐乐是我", "我是天天 天天是我"]
    out = correct_segments(segs, lines)
    assert out[0].text == "我是乐乐 乐乐是我"
    assert out[1].text == "我是天天 天天是我"   # order disambiguates the tie


def test_correct_segments_line_can_repeat_across_segments():
    """A single script line may span two whisper segments; the cursor must not
    advance past a line if the next segment also best-matches it."""
    segs = [
        CaptionSegment(start=0.0, end=1.0, text="我是乐乐"),
        CaptionSegment(start=1.0, end=2.0, text="乐乐是我"),
    ]
    lines = ["我是乐乐", "乐乐是我"]
    out = correct_segments(segs, lines)
    assert [s.text for s in out] == ["我是乐乐", "乐乐是我"]
