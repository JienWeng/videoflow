"""Phase 0: per-dimension QAResult (backward-compatible) + supervision thresholds."""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.config import Settings
from app.schemas.qa_schema import DimensionScore, QAResult
from app.services import settings_service


def test_qaresult_back_compat_without_dimensions():
    # Old shape (no dimensions) must still validate, and old qa_json rows load.
    r = QAResult(score=8, passed=True, issues=[], recommendation="accept")
    assert r.dimensions == []
    assert r.worst_dimension is None
    # round-trip an old persisted dict
    assert QAResult.model_validate(r.model_dump()).score == 8


def test_qaresult_with_dimensions():
    r = QAResult(
        score=6,
        passed=False,
        issues=["frame 3: outfit changed"],
        recommendation="regenerate",
        dimensions=[
            DimensionScore(name="character_consistency", score=2, evidence=["frame 3: outfit changed"]),
            DimensionScore(name="continuity", score=4),
        ],
        worst_dimension="character_consistency",
    )
    assert r.dimension("character_consistency") == 2
    assert r.dimension("artifacts_text") is None
    assert r.worst_dimension == "character_consistency"


def test_dimension_score_bounds():
    with pytest.raises(Exception):
        DimensionScore(name="continuity", score=6)
    with pytest.raises(Exception):
        DimensionScore(name="continuity", score=0)


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, MINIMAX_API_KEY="mk", ATLASCLOUD_API_KEY="ak", **kw)


@pytest.fixture
def session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_supervision_thresholds_resolve_defaults(session):
    s = _settings()
    assert settings_service.resolve(session, "qa_accept_score", default=None, settings=s) == 7
    assert settings_service.resolve(session, "qa_max_attempts", default=None, settings=s) == 2
    assert settings_service.resolve(session, "supervision_enabled", default=None, settings=s) is False
    assert settings_service.resolve(session, "run_budget_units", default=None, settings=s) == 400


def test_supervision_threshold_override(session):
    s = _settings()
    settings_service.set_app_setting(session, "qa_accept_score", 9)
    assert settings_service.resolve(session, "qa_accept_score", default=None, settings=s) == 9
