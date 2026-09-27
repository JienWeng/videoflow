"""Unit tests for op_service per-kind result summarizers."""

from __future__ import annotations

from types import SimpleNamespace
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

import pytest

from app.services.op_service import list_project_ops, summarize_result, update_op_progress
from app.models import Op


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


def test_update_op_progress_persists_stage_history():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        op = Op(kind="video_generation", project_id="project_1")
        session.add(op)
        session.commit()

        update_op_progress(session, op.id, "story")
        update_op_progress(session, op.id, "scenes")

        stored = session.get(Op, op.id)
        assert stored.project_id == "project_1"
        assert stored.result_json == {"stage": "scenes", "stages": ["story", "scenes"]}


def test_list_project_ops_only_returns_requested_project():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            Op(kind="video_generation", project_id="project_1"),
            Op(kind="video_generation", project_id="project_2"),
        ])
        session.commit()
        rows = list_project_ops(session, "project_1", kind="video_generation")
    assert len(rows) == 1
    assert rows[0].project_id == "project_1"
