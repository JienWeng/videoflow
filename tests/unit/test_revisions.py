"""Unit tests for the revision diff helper."""

from __future__ import annotations

from app.services.scene_service import diff_fields


def test_diff_fields_returns_only_changed():
    current = {"title": "old", "summary": "same", "duration": 5}
    incoming = {"title": "new", "summary": "same", "duration": 7}
    assert diff_fields(current, incoming) == {"title": "old", "duration": 5}


def test_diff_fields_excludes_none_incoming():
    current = {"title": "old", "summary": "keep"}
    incoming = {"title": "new", "summary": None}
    assert diff_fields(current, incoming) == {"title": "old"}


def test_diff_fields_no_change_is_empty():
    current = {"title": "same", "duration": 5}
    incoming = {"title": "same", "duration": 5}
    assert diff_fields(current, incoming) == {}


def test_diff_fields_empty_incoming():
    assert diff_fields({"a": 1}, {}) == {}


def test_diff_fields_list_values():
    current = {"asset_ids": ["a", "b"]}
    assert diff_fields(current, {"asset_ids": ["a"]}) == {"asset_ids": ["a", "b"]}
    assert diff_fields(current, {"asset_ids": ["a", "b"]}) == {}
