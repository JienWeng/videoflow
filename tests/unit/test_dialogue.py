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

    def test_over_60_chars_inside_quotes_is_false(self):
        assert has_dialogue("Grace says 「" + "a" * 61 + "」") is False

    def test_exactly_60_chars_inside_quotes_is_true(self):
        assert has_dialogue("Grace says 「" + "a" * 60 + "」") is True

    def test_western_quotes_do_not_count(self):
        assert has_dialogue('Grace says "Hello!"') is False
