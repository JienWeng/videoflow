"""Unit tests for @Name mention detection (linking_service.find_mentions)
and bare-name auto-tagging (linking_service.tag_bare_names)."""

from __future__ import annotations

from app.services.linking_service import find_mentions, tag_bare_names


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


# --- tag_bare_names: bare entity names -> @Name, never inside 「」 dialogue ---


def test_bare_name_tagged_and_reported():
    text, ids = tag_bare_names("Grace waves at camera", {"Grace": "char_1"})
    assert text == "@Grace waves at camera"
    assert ids == ["char_1"]


def test_bare_name_inside_dialogue_untouched_and_not_linked():
    # A name spoken in dialogue is speech, not a visual reference: no rewrite,
    # no link — captions/voice must extract the quoted line verbatim.
    text, ids = tag_bare_names("she says 「Grace 真棒」", {"Grace": "char_1"})
    assert text == "she says 「Grace 真棒」"
    assert ids == []


def test_bare_name_outside_dialogue_tagged_inside_untouched():
    src = "Grace lifts the cup and says 「Grace 真棒」"
    text, ids = tag_bare_names(src, {"Grace": "char_1"})
    assert text == "@Grace lifts the cup and says 「Grace 真棒」"
    assert ids == ["char_1"]


def test_already_tagged_no_double_tag_id_still_reported():
    text, ids = tag_bare_names("@Grace waves", {"Grace": "char_1"})
    assert text == "@Grace waves"
    assert ids == ["char_1"]


def test_already_tagged_later_bare_occurrence_left_alone():
    src = "@Grace waves, then Grace smiles"
    text, ids = tag_bare_names(src, {"Grace": "char_1"})
    assert text == src
    assert ids == ["char_1"]


def test_first_occurrence_tagged_later_bare_left_alone():
    text, ids = tag_bare_names("Grace waves, then Grace smiles", {"Grace": "char_1"})
    assert text == "@Grace waves, then Grace smiles"
    assert ids == ["char_1"]


def test_word_boundary_graceland_safe():
    text, ids = tag_bare_names("welcome to Graceland", {"Grace": "char_1"})
    assert text == "welcome to Graceland"
    assert ids == []


def test_cjk_embedded_name_not_spliced():
    # CJK chars are \w: 乐乐 inside a longer run must not be tagged.
    text, ids = tag_bare_names("乐乐是我的朋友", {"乐乐": "char_lele"})
    assert text == "乐乐是我的朋友"
    assert ids == []


def test_cjk_name_with_boundary_tagged():
    text, ids = tag_bare_names("乐乐 走过草地", {"乐乐": "char_lele"})
    assert text == "@乐乐 走过草地"
    assert ids == ["char_lele"]


def test_one_char_name_skipped():
    text, ids = tag_bare_names("乐 在草地上", {"乐": "char_le"})
    assert text == "乐 在草地上"
    assert ids == []


def test_multiple_names_all_tagged():
    names = {"Grace": "char_1", "Meadow": "asset_bg"}
    text, ids = tag_bare_names("Grace sits on the Meadow", names)
    assert text == "@Grace sits on the @Meadow"
    assert set(ids) == {"char_1", "asset_bg"}


def test_longest_name_wins_no_splice():
    names = {"Red Cup": "asset_1", "Red Cup Deluxe": "asset_2"}
    text, ids = tag_bare_names("place the Red Cup Deluxe here", names)
    assert text == "place the @Red Cup Deluxe here"
    assert ids == ["asset_2"]


def test_long_and_short_names_both_present():
    names = {"Red Cup": "asset_1", "Red Cup Deluxe": "asset_2"}
    text, ids = tag_bare_names("Red Cup next to Red Cup Deluxe", names)
    assert text == "@Red Cup next to @Red Cup Deluxe"
    assert set(ids) == {"asset_1", "asset_2"}


def test_tagged_long_name_does_not_let_short_splice():
    # "@Red Cup Deluxe" already tagged; a bare "Red Cup Deluxe" later must not
    # have "Red Cup" spliced into its prefix.
    names = {"Red Cup": "asset_1", "Red Cup Deluxe": "asset_2"}
    src = "@Red Cup Deluxe beside Red Cup Deluxe"
    text, ids = tag_bare_names(src, names)
    assert text == src
    assert ids == ["asset_2"]


def test_tag_bare_names_empty_text():
    assert tag_bare_names("", {"Grace": "char_1"}) == ("", [])


def test_tag_bare_names_empty_names():
    assert tag_bare_names("Grace waves", {}) == ("Grace waves", [])


def test_tag_bare_names_case_sensitive():
    text, ids = tag_bare_names("grace waves", {"Grace": "char_1"})
    assert text == "grace waves"
    assert ids == []
