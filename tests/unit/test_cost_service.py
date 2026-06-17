"""Phase 1: budget governor — cost model + RunBudget tracking."""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.config import Settings
from app.services import cost_service


@pytest.fixture
def session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, MINIMAX_API_KEY="mk", ATLASCLOUD_API_KEY="ak", **kw)


def test_estimate_call_uses_config_units(session):
    s = _settings()
    assert cost_service.estimate_call(session, "text", settings=s) == 1
    assert cost_service.estimate_call(session, "vision", settings=s) == 2
    assert cost_service.estimate_call(session, "image", settings=s) == 10


def test_estimate_video_scales_with_duration(session):
    s = _settings()
    # 30 units/second, duration clamped to [3,15]
    assert cost_service.estimate_video(session, 5, settings=s) == 150
    assert cost_service.estimate_video(session, 100, settings=s) == 30 * 15  # clamp hi
    assert cost_service.estimate_video(session, 1, settings=s) == 30 * 3     # clamp lo


def test_open_run_uses_default_budget(session):
    s = _settings()
    b = cost_service.open_run(session, workflow_run_id="wf1", settings=s)
    assert b.limit_units == 400  # config default run_budget_units
    assert b.spent_units == 0
    assert b.status == "open"


def test_charge_accumulates_and_exhausts(session):
    s = _settings()
    b = cost_service.open_run(session, workflow_run_id="wf1", limit_units=100, settings=s)
    b = cost_service.charge(session, b.id, "image")  # 10
    assert b.spent_units == 10 and b.status == "open"
    cost_service.charge(session, b.id, units=95)      # explicit units
    b = cost_service.get_budget(session, b.id)
    assert b.spent_units == 105 and b.status == "exhausted"


def test_can_afford(session):
    s = _settings()
    b = cost_service.open_run(session, workflow_run_id="wf1", limit_units=100, settings=s)
    assert cost_service.can_afford(session, b.id, 90) is True
    assert cost_service.can_afford(session, b.id, 200) is False


def test_remaining(session):
    s = _settings()
    b = cost_service.open_run(session, workflow_run_id="wf1", limit_units=100, settings=s)
    cost_service.charge(session, b.id, units=30)
    assert cost_service.remaining(session, b.id) == 70


def test_find_by_workflow_run(session):
    s = _settings()
    b = cost_service.open_run(session, workflow_run_id="wfX", limit_units=50, settings=s)
    found = cost_service.budget_for_run(session, workflow_run_id="wfX")
    assert found is not None and found.id == b.id
