"""Unit tests for op_service per-kind result summarizers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.op_service import summarize_result


def test_summarize_storyboard():
    asset = SimpleNamespace(id="asset_1", name="Storyboard", file_path="/p/sb.png")
    assert summarize_result("storyboard", asset) == {
        "asset_id": "asset_1",
        "name": "Storyboard",
        "file_path": "/p/sb.png",
    }


def test_summarize_assets_list():
    assets = [
        SimpleNamespace(id="asset_1", name="Red Cup"),
        SimpleNamespace(id="asset_2", name="Blanket"),
    ]
    assert summarize_result("assets", assets) == {
        "asset_ids": ["asset_1", "asset_2"],
        "names": ["Red Cup", "Blanket"],
    }


def test_summarize_caption():
    out = SimpleNamespace(id="out_1", captioned_path="/p/c.mp4")
    assert summarize_result("caption", out) == {
        "output_id": "out_1",
        "captioned_path": "/p/c.mp4",
    }


def test_summarize_style_ingest():
    style = SimpleNamespace(id="style_1", name="Project style")
    assert summarize_result("style_ingest", style) == {
        "style_guide_id": "style_1",
        "name": "Project style",
    }


def test_summarize_unknown_kind_rejected():
    with pytest.raises(KeyError):
        summarize_result("nope", object())
