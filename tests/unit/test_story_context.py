"""story_context — overall story + sibling scenes for cross-scene continuity."""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.models import Asset, Character, Scene, Script
from app.services.scene_service import story_context


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_story_context_with_script_and_siblings(session):
    script = Script(id="script_1", idea="a cat learns to fly",
                    title="Sky Cat", summary="a cat's flying journey")
    session.add(script)
    session.add(Scene(id="sc_1", title="Takeoff", summary="cat jumps", script_id="script_1"))
    session.add(Scene(id="sc_2", title="Flight", summary="cat soars", script_id="script_1"))
    session.add(Scene(id="sc_other", title="Unrelated", summary="another story"))
    session.commit()

    ctx = story_context(session, session.get(Scene, "sc_1"))
    assert ctx["story"] == {
        "idea": "a cat learns to fly",
        "title": "Sky Cat",
        "summary": "a cat's flying journey",
    }
    # Only same-script siblings, never the scene itself.
    assert ctx["other_scenes"] == [{"title": "Flight", "summary": "cat soars"}]


def test_story_context_carries_generation_brief_to_later_stages(session):
    brief = {"language": "Malay", "instruction": "Keep the narration gentle"}
    session.add(Script(
        id="script_brief", idea="a cat story", title="Cat", summary="Journey",
        draft_json={"generation_brief": brief},
    ))
    session.add(Scene(id="scene_brief", title="Start", summary="First scene", script_id="script_brief"))
    session.commit()

    ctx = story_context(session, session.get(Scene, "scene_brief"))

    assert ctx["generation_brief"] == brief


def test_story_context_without_script_uses_all_other_scenes(session):
    session.add(Scene(id="sc_1", title="A", summary="first"))
    session.add(Scene(id="sc_2", title="B", summary="second"))
    session.commit()

    ctx = story_context(session, session.get(Scene, "sc_1"))
    assert "story" not in ctx
    assert ctx["other_scenes"] == [{"title": "B", "summary": "second"}]


def test_story_context_lone_scene_returns_none(session):
    session.add(Scene(id="sc_1", title="A", summary="only one"))
    session.commit()
    assert story_context(session, session.get(Scene, "sc_1")) is None


def test_story_context_truncates_sibling_summaries(session):
    session.add(Scene(id="sc_1", title="A", summary="x"))
    session.add(Scene(id="sc_2", title="B", summary="y" * 500))
    session.commit()
    ctx = story_context(session, session.get(Scene, "sc_1"))
    assert ctx["other_scenes"][0]["summary"] == "y" * 200


def test_story_context_includes_ranked_continuity_records(session):
    session.add(Scene(id="sc_1", title="Station", summary="Maya enters the station"))
    session.add(Character(id="char_maya", name="Maya", appearance="red coat"))
    session.add(Asset(id="asset_clock", name="station clock", description="east wall"))
    session.commit()
    ctx = story_context(session, session.get(Scene, "sc_1"))
    assert ctx["continuity"][0]["kind"] == "character"
    assert ctx["continuity"][0]["text"] == "Maya red coat"
