"""Unit tests for @Name mention detection (linking_service.find_mentions)."""

from __future__ import annotations

from app.services.linking_service import find_mentions


def test_exact_match():
    assert find_mentions("Mid-shot: @Grace waves", {"Grace": "char_1"}) == ["char_1"]


def test_no_mention_returns_empty():
    assert find_mentions("Grace waves, no at-sign", {"Grace": "char_1"}) == []


def test_empty_text():
    assert find_mentions("", {"Grace": "char_1"}) == []


def test_empty_names():
    assert find_mentions("@Grace waves", {}) == []


def test_ascii_boundary_not_substring():
    # @Graceland must NOT match the name "Grace".
    assert find_mentions("welcome to @Graceland", {"Grace": "char_1"}) == []


def test_ascii_match_at_end_of_string():
    assert find_mentions("a wave from @Grace", {"Grace": "char_1"}) == ["char_1"]


def test_ascii_match_followed_by_punctuation():
    assert find_mentions("hello @Grace, hi", {"Grace": "char_1"}) == ["char_1"]


def test_longest_name_wins():
    names = {"Red Cup": "asset_1", "Red Cup Deluxe": "asset_2"}
    # Only the longer name is present; the shorter must not also fire on its prefix.
    assert find_mentions("place the @Red Cup Deluxe here", names) == ["asset_2"]


def test_both_long_and_short_when_present():
    names = {"Red Cup": "asset_1", "Red Cup Deluxe": "asset_2"}
    got = find_mentions("@Red Cup next to @Red Cup Deluxe", names)
    assert set(got) == {"asset_1", "asset_2"}


def test_cjk_match_with_space():
    assert find_mentions("@乐乐 走过草地", {"乐乐": "char_lele"}) == ["char_lele"]


def test_cjk_match_at_end():
    assert find_mentions("镜头对准@乐乐", {"乐乐": "char_lele"}) == ["char_lele"]


def test_cjk_followed_by_word_char_no_match():
    # Conservative: CJK chars are \w, so "@乐乐是我" does NOT match 乐乐.
    assert find_mentions("@乐乐是我", {"乐乐": "char_lele"}) == []


def test_cjk_followed_by_punctuation_matches():
    assert find_mentions("@乐乐,你好", {"乐乐": "char_lele"}) == ["char_lele"]


def test_multiple_mentions():
    names = {"Grace": "char_1", "Meadow": "asset_bg", "乐乐": "char_lele"}
    got = find_mentions("@Grace and @乐乐 sit on the @Meadow.", names)
    assert set(got) == {"char_1", "asset_bg", "char_lele"}


def test_no_duplicate_ids():
    assert find_mentions("@Grace then @Grace again", {"Grace": "char_1"}) == ["char_1"]


def test_case_sensitive():
    assert find_mentions("@grace waves", {"Grace": "char_1"}) == []
