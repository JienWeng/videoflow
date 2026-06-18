"""Unit tests for the per-shot dialogue detection helper."""

from __future__ import annotations

from app.services.dialogue import has_dialogue


class TestHasDialogue:
    def test_prompt_with_quoted_line_is_true(self):
        assert has_dialogue("@Grace waves and says, 「Hello there!」") is True

    def test_chinese_dialogue_is_true(self):
        assert has_dialogue("@Grace 说：「你好呀！」") is True

    def test_multiple_lines_is_true(self):
        assert has_dialogue("「Hi!」 then later 「Bye!」") is True

    def test_empty_string_is_false(self):
        assert has_dialogue("") is False

    def test_no_quotes_is_false(self):
        assert has_dialogue("Grace waves at the camera, smiling") is False

    def test_empty_quotes_is_false(self):
        assert has_dialogue("Grace says 「」 nothing") is False

    def test_long_duration_filling_line_is_true(self):
        # Lines are now sized to fill the shot at ~170-200 WPM; a ~90-char line
        # (a 6s shot) must count as dialogue (the old 60-char cap forced slow,
        # too-short lines). The cap is a generous 220.
        assert has_dialogue("Grace says 「" + "a" * 90 + "」") is True

    def test_absurdly_long_line_is_false(self):
        assert has_dialogue("Grace says 「" + "a" * 221 + "」") is False

    def test_western_quotes_do_not_count(self):
        assert has_dialogue('Grace says "Hello!"') is False


def test_preserve_dialogue_empty_refined_has_no_leading_space():
    from app.services.refine_service import _preserve_dialogue

    out = _preserve_dialogue("Grace says, 「Hello!」", "")
    assert out == "「Hello!」"
