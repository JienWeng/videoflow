"""Unit tests for the settings service: catalog, override validation, merge."""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.config import Settings
from app.errors import NotFoundError, ValidationFailedError
from app.llm import skills
from app.services import settings_service


@pytest.fixture
def session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture(autouse=True)
def _clean_overrides():
    skills.clear_overrides()
    yield
    skills.clear_overrides()


def _settings(**kw) -> Settings:
    base = {
        "MINIMAX_API_KEY": "mk",
        "ATLASCLOUD_API_KEY": "ak",
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "GEMINI_API_KEY": "",
    }
    base.update(kw)
    return Settings(_env_file=None, **base)


def test_available_providers_reflects_configured_keys():
    cat = settings_service.available_providers(_settings(ANTHROPIC_API_KEY="x"))
    by = {c["name"]: c for c in cat}
    assert by["minimax"]["configured"] is True
    assert by["atlas"]["configured"] is True
    assert by["anthropic"]["configured"] is True
    assert by["openai"]["configured"] is False
    assert by["gemini"]["configured"] is False
    # curated models present, default merged in.
    assert "MiniMax-Text-01" in by["minimax"]["models"]


def test_set_override_rejects_unconfigured_provider(session):
    with pytest.raises(ValidationFailedError):
        settings_service.set_override(
            session, "script_agent", "openai", "gpt-4o", _settings()
        )


def test_set_override_accepts_free_typed_model(session):
    # Model ids are free-typed now: any non-empty id for a configured provider is
    # accepted (curated lists are suggestions only, not an allowlist).
    out = settings_service.set_override(
        session, "script_agent", "minimax", "bogus-model", _settings()
    )
    assert out["model"] == "bogus-model"


def test_set_override_rejects_unknown_agent(session):
    with pytest.raises(NotFoundError):
        settings_service.set_override(
            session, "nope_agent", "minimax", "MiniMax-M2", _settings()
        )


def test_effective_skill_merge(session):
    s = _settings()
    settings_service.set_override(session, "script_agent", "minimax", "MiniMax-M2", s)
    eff = settings_service.effective_skill(session, "script_agent")
    assert eff.provider == "minimax"
    assert eff.model == "MiniMax-M2"
    # other agents untouched.
    other = settings_service.effective_skill(session, "scene_agent")
    base = skills.get_skill("scene_agent")
    assert other.provider == base.provider and other.model == base.model


def test_clear_override_reverts(session):
    s = _settings()
    settings_service.set_override(session, "script_agent", "minimax", "MiniMax-M2", s)
    settings_service.set_override(session, "script_agent", None, None, s)
    eff = settings_service.effective_skill(session, "script_agent")
    base = skills.get_skill("script_agent")
    assert eff.provider == base.provider and eff.model == base.model
    assert "script_agent" not in settings_service.get_overrides(session)


def test_load_overrides_populates_mirror(session):
    s = _settings()
    settings_service.set_override(session, "qa_agent", "atlas", "glm-5v", s)
    skills.clear_overrides()
    assert skills.get_effective_skill("qa_agent").model != "glm-5v"
    settings_service.load_overrides(session)
    assert skills.get_effective_skill("qa_agent").model == "glm-5v"
