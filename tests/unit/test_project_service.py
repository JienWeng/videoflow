"""project_service — lazy default project, orphan adoption, activation, deletion."""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401
from app.errors import NotFoundError, ValidationFailedError
from app.models import (
    Asset,
    Character,
    Project,
    Op,
    RenderJob,
    RenderOutput,
    Scene,
    Script,
    Shot,
    StyleGuide,
)
from app.services import project_service


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_get_active_lazily_creates_default_project(session):
    assert session.exec(select(Project)).all() == []
    active = project_service.get_active(session)
    assert active.name == "My project"
    assert active.is_active is True
    # Idempotent: a second call returns the same project, no duplicate.
    again = project_service.get_active(session)
    assert again.id == active.id
    assert len(session.exec(select(Project)).all()) == 1


def test_get_active_adopts_orphan_rows(session):
    # Rows seeded with project_id NULL (pre-migration data / test fixtures).
    session.add(Character(id="char_1", name="Grace"))
    session.add(Asset(id="asset_1", name="Cup"))
    session.add(Scene(id="scene_1", title="S1"))
    session.add(Script(id="script_1", title="T"))
    session.add(StyleGuide(id="style_1"))
    session.add(RenderJob(id="job_1"))
    session.commit()

    active = project_service.get_active(session)

    for model, row_id in [
        (Character, "char_1"), (Asset, "asset_1"), (Scene, "scene_1"),
        (Script, "script_1"), (StyleGuide, "style_1"), (RenderJob, "job_1"),
    ]:
        session.expire_all()
        assert session.get(model, row_id).project_id == active.id


def test_orphans_seeded_after_bootstrap_are_still_adopted(session):
    active = project_service.get_active(session)
    session.add(Scene(id="scene_late", title="late"))
    session.commit()
    # While there's a single project, get_active keeps sweeping orphans.
    project_service.get_active(session)
    session.expire_all()
    assert session.get(Scene, "scene_late").project_id == active.id


def test_orphans_never_adopted_into_a_second_project(session):
    project_service.get_active(session)
    b = project_service.create_project(session, name="B")
    project_service.activate(session, b.id)
    session.add(Scene(id="scene_x", title="x"))
    session.commit()
    project_service.get_active(session)
    session.expire_all()
    assert session.get(Scene, "scene_x").project_id is None


def test_activate_is_exclusive(session):
    a = project_service.get_active(session)
    b = project_service.create_project(session, name="B")
    assert b.is_active is False

    project_service.activate(session, b.id)
    session.expire_all()
    assert session.get(Project, b.id).is_active is True
    assert session.get(Project, a.id).is_active is False
    assert project_service.get_active(session).id == b.id

    with pytest.raises(NotFoundError):
        project_service.activate(session, "project_nope")


def test_activate_cannot_switch_projects_during_video_generation(session):
    active = project_service.get_active(session)
    other = project_service.create_project(session, name="B")
    session.add(Op(kind="video_generation", status="running", project_id=active.id))
    session.commit()

    with pytest.raises(ValidationFailedError, match="video generation is still running"):
        project_service.activate(session, other.id)

    assert project_service.get_active(session).id == active.id


def test_delete_active_project_rejected(session):
    active = project_service.get_active(session)
    with pytest.raises(ValidationFailedError):
        project_service.delete_project(session, active.id)


def test_delete_project_removes_its_rows_but_not_others(session):
    a = project_service.get_active(session)
    session.add(Scene(id="scene_a", title="A's scene", project_id=a.id))
    session.commit()

    b = project_service.create_project(session, name="B")
    session.add(Character(id="char_b", name="Bob", project_id=b.id))
    session.add(Asset(id="asset_b", name="Hat", project_id=b.id))
    session.add(Scene(id="scene_b", title="B scene", project_id=b.id))
    session.add(Shot(id="shot_b", scene_id="scene_b", prompt="p"))
    session.add(Script(id="script_b", project_id=b.id))
    session.add(StyleGuide(id="style_b", project_id=b.id))
    session.add(RenderJob(id="job_b", project_id=b.id))
    session.add(RenderOutput(id="out_b", render_job_id="job_b"))
    session.commit()

    deleted = project_service.delete_project(session, b.id)
    assert deleted == {
        "scenes": 1, "shots": 1, "render_jobs": 1, "render_outputs": 1,
        "characters": 1, "assets": 1, "scripts": 1, "style_guides": 1,
    }
    for model, row_id in [
        (Project, b.id), (Character, "char_b"), (Asset, "asset_b"),
        (Scene, "scene_b"), (Shot, "shot_b"), (Script, "script_b"),
        (StyleGuide, "style_b"), (RenderJob, "job_b"), (RenderOutput, "out_b"),
    ]:
        assert session.get(model, row_id) is None
    # A's data untouched.
    assert session.get(Scene, "scene_a") is not None
    assert session.get(Project, a.id) is not None


def test_counts(session):
    a = project_service.get_active(session)
    session.add(Scene(project_id=a.id))
    session.add(Scene(project_id=a.id))
    session.add(Character(name="X", project_id=a.id))
    session.add(Asset(project_id=a.id))
    session.add(Script(project_id=a.id))
    session.add(Scene(project_id="project_other"))
    session.commit()

    assert project_service.counts(session, a.id) == {
        "scenes": 2, "characters": 1, "assets": 1, "scripts": 1,
    }


def test_update_project_partial(session):
    a = project_service.get_active(session)
    updated = project_service.update_project(session, a.id, name="Renamed")
    assert updated.name == "Renamed"
    assert updated.description == ""
    updated = project_service.update_project(session, a.id, description="d")
    assert updated.name == "Renamed"
    assert updated.description == "d"


def test_list_projects_bootstraps_and_orders(session):
    projects = project_service.list_projects(session)
    assert len(projects) == 1
    project_service.create_project(session, name="B")
    names = [p.name for p in project_service.list_projects(session)]
    assert names == ["My project", "B"]
