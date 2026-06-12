"""project_state — the deterministic pipeline snapshot behind state-aware chat.

next_steps ordering is pure code (no LLM): onboarding for empty projects,
per-scene first-missing step otherwise, captions/next-story when done.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.models import (
    Asset,
    Character,
    RenderJob,
    Scene,
    Script,
    Shot,
    StyleGuide,
)
from app.models.render_job import RenderStatus
from app.services.chat_service import project_state


@pytest.fixture()
def session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_empty_project_gives_three_ordered_onboarding_steps(session):
    state = project_state(session)
    assert state["characters"] == 0
    assert state["has_style"] is False
    assert state["scripts"] == 0
    assert state["scenes"] == []
    steps = state["next_steps"]
    assert len(steps) == 3
    assert "character" in steps[0].lower()
    assert "style" in steps[1].lower()
    assert "script" in steps[2].lower()


def test_onboarding_skips_satisfied_steps(session):
    session.add(Character(name="乐乐"))
    session.commit()
    steps = project_state(session)["next_steps"]
    assert all("character" not in s.lower() for s in steps)
    assert "style" in steps[0].lower()


def test_scene_missing_shots_yields_shots_step_with_title(session):
    session.add(Character(name="乐乐"))
    session.add(StyleGuide())
    session.add(Script(title="story"))
    session.add(Scene(id="scene_1", title="我是乐乐",
                      scene_json={"a": 1, "b": 2}))  # expanded stub
    session.commit()
    state = project_state(session)
    sc = state["scenes"][0]
    assert sc["expanded"] is True
    assert sc["has_shots"] is False
    steps = state["next_steps"]
    assert "shot" in steps[0].lower()
    assert "我是乐乐" in steps[0]


def test_unexpanded_scene_yields_expand_step_first(session):
    session.add(Scene(id="scene_1", title="开场", scene_json={"stub": True}))
    session.commit()
    state = project_state(session)
    assert state["scenes"][0]["expanded"] is False
    assert "开场" in state["next_steps"][0]
    assert "expand" in state["next_steps"][0].lower()


def test_scene_steps_capped_at_three(session):
    for i in range(5):
        session.add(Scene(id=f"scene_{i}", title=f"场景{i}",
                          scene_json={"stub": True}))
    session.commit()
    assert len(project_state(session)["next_steps"]) == 3


def test_all_rendered_suggests_captions_or_next_story(session):
    session.add(Scene(id="scene_1", title="我是乐乐",
                      scene_json={"a": 1, "b": 2}))
    session.add(Shot(id="shot_1", scene_id="scene_1"))
    session.add(Asset(type="storyboard", metadata_json={"scene_id": "scene_1"}))
    session.add(RenderJob(scene_id="scene_1", shot_id=None,
                          status=RenderStatus.succeeded))
    session.commit()
    state = project_state(session)
    sc = state["scenes"][0]
    assert sc["has_shots"] and sc["has_storyboard"] and sc["rendered"]
    steps = state["next_steps"]
    assert len(steps) >= 1
    assert "caption" in steps[0].lower()


def test_render_with_shot_id_does_not_count_as_scene_render(session):
    session.add(Scene(id="scene_1", title="t", scene_json={"a": 1, "b": 2}))
    session.add(Shot(id="shot_1", scene_id="scene_1"))
    session.add(RenderJob(scene_id="scene_1", shot_id="shot_1",
                          status=RenderStatus.succeeded))
    session.commit()
    assert project_state(session)["scenes"][0]["rendered"] is False
