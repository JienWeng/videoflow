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


# ---------------------------------------------------------------------------
# Shot-duration-aware (timed) caption alignment
# ---------------------------------------------------------------------------

from app.services.caption_service import correct_segments_timed, timed_script_lines


class TestTimedScriptLines:
    def test_windows_are_cumulative_and_silent_entries_keep_timeline(self):
        """3 entries (3s/2s/3s); lines in entries 1 and 3, entry 2 silent.
        Entry 2 contributes its duration to the timeline but no line, so the
        windows are [0,3] and [5,8]."""
        spec = {
            "prompt": "whole-scene prompt without quotes",
            "multi_prompt": [
                {"index": 1, "prompt": "乐乐 says 「我是乐乐 乐乐是我」", "duration": 3},
                {"index": 2, "prompt": "The kitten just meows", "duration": 2},
                {"index": 3, "prompt": "天天 says 「我是天天 天天是我」", "duration": 3},
            ],
        }
        assert timed_script_lines(spec) == [
            {"text": "我是乐乐 乐乐是我", "start": 0.0, "end": 3.0},
            {"text": "我是天天 天天是我", "start": 5.0, "end": 8.0},
        ]

    def test_empty_or_missing_spec(self):
        assert timed_script_lines(None) == []
        assert timed_script_lines({}) == []
        assert timed_script_lines({"prompt": "「有台词」 but no multi_prompt"}) == []

    def test_entries_without_durations_yield_nothing(self):
        spec = {"multi_prompt": [{"prompt": "「我是乐乐」"}]}
        assert timed_script_lines(spec) == []

    def test_index_field_orders_entries(self):
        spec = {
            "multi_prompt": [
                {"index": 2, "prompt": "「第二句」", "duration": 2},
                {"index": 1, "prompt": "「第一句」", "duration": 3},
            ],
        }
        assert timed_script_lines(spec) == [
            {"text": "第一句", "start": 0.0, "end": 3.0},
            {"text": "第二句", "start": 3.0, "end": 5.0},
        ]


class TestCorrectSegmentsTimed:
    # Windows: line A in [0,3], line B in [5,8] (homophone-tie pair).
    TIMED = [
        {"text": "我是天天 天天是我", "start": 0.0, "end": 3.0},
        {"text": "我是田田 田田是我", "start": 5.0, "end": 8.0},
    ]

    def test_window_overlap_disambiguates_fuzzy_tie(self):
        """天天/田田 are homophones: the misheard text fuzzy-ties against BOTH
        lines, but only window 1 overlaps the 0.5-2.5s segment — so the
        window-1 line wins purely on time."""
        segs = [CaptionSegment(start=0.5, end=2.5, text="我是甜甜 甜甜是我")]
        out = correct_segments_timed(segs, self.TIMED)
        assert out[0].text == "我是天天 天天是我"
        assert (out[0].start, out[0].end) == (0.5, 2.5)

    def test_segment_outside_all_windows_keeps_whisper_text(self):
        segs = [CaptionSegment(start=10.0, end=12.0, text="窗外的喵喵叫")]
        out = correct_segments_timed(segs, self.TIMED)
        assert out[0].text == "窗外的喵喵叫"

    def test_below_threshold_mismatch_keeps_whisper_text(self):
        # Overlaps window 1 but shares nothing with its line -> below 0.35.
        segs = [CaptionSegment(start=1.0, end=2.0, text="completely unrelated english")]
        out = correct_segments_timed(segs, self.TIMED)
        assert out[0].text == "completely unrelated english"

    def test_no_timed_lines_is_noop(self):
        segs = [CaptionSegment(start=0, end=1, text="hello")]
        assert correct_segments_timed(segs, []) == segs


class TestDefaultCaptionStyle:
    """default_caption_style derives the caption preset from the StyleGuide."""

    class _Style:
        def __init__(self, audience):
            self.audience = audience

    def test_no_style_guide_keeps_kids_default(self):
        from app.services.caption_service import default_caption_style

        assert default_caption_style(None) == "kids"

    @pytest.mark.parametrize(
        "audience",
        ["children aged 3-6", "Kids learning Mandarin", "儿童", "幼儿园小班", "面向小朋友的科普"],
    )
    def test_child_audience_picks_kids(self, audience):
        from app.services.caption_service import default_caption_style

        assert default_caption_style(self._Style(audience)) == "kids"

    @pytest.mark.parametrize("audience", ["young adults", "tech professionals", "", None])
    def test_general_audience_picks_clean(self, audience):
        from app.services.caption_service import default_caption_style

        assert default_caption_style(self._Style(audience)) == "clean"

    def test_keyword_match_is_case_insensitive(self):
        from app.services.caption_service import default_caption_style

        assert default_caption_style(self._Style("CHILDREN and parents")) == "kids"

    def test_default_is_a_known_style(self):
        from app.services.caption_service import default_caption_style

        assert default_caption_style(None) in STYLES
        assert default_caption_style(self._Style("adults")) in STYLES


# ---------------------------------------------------------------------------
# Caption editor — segment validation for user-edited subtitle lines
# ---------------------------------------------------------------------------

from app.errors import ValidationFailedError
from app.services.caption_service import validate_segments


class TestValidateSegments:
    def test_strips_text_drops_empty_and_sorts_by_start(self):
        segs = validate_segments(
            [
                {"start": 3.0, "end": 5.0, "text": "second"},
                {"start": 0.0, "end": 2.0, "text": "  first "},
                {"start": 5.0, "end": 6.0, "text": "   "},  # dropped silently
            ]
        )
        assert [s.text for s in segs] == ["first", "second"]
        assert [s.start for s in segs] == [0.0, 3.0]
        assert all(isinstance(s, CaptionSegment) for s in segs)

    def test_rejects_end_not_after_start(self):
        with pytest.raises(ValidationFailedError):
            validate_segments([{"start": 2.0, "end": 2.0, "text": "x"}])
        with pytest.raises(ValidationFailedError):
            validate_segments([{"start": 3.0, "end": 1.0, "text": "x"}])

    def test_rejects_negative_start(self):
        with pytest.raises(ValidationFailedError):
            validate_segments([{"start": -0.5, "end": 2.0, "text": "x"}])

    def test_requires_at_least_one_nonempty_segment(self):
        with pytest.raises(ValidationFailedError):
            validate_segments([])
        with pytest.raises(ValidationFailedError):
            validate_segments([{"start": 0.0, "end": 1.0, "text": "  "}])
