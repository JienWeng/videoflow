"""Unit tests for Agent Studio service layer: customization persistence,
validation, reset, and detail view."""

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
def _clean():
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


# ----------------------------------------------------------- persistence
def test_set_customization_overrides_prompt_and_config(session):
    settings_service.set_customization(
        session,
        "script_agent",
        system_prompt="Write only haiku.",
        temperature=0.1,
        max_retries=5,
        settings=_settings(),
    )
    eff = settings_service.effective_skill(session, "script_agent")
    assert eff.system_prompt == "Write only haiku."
    assert eff.temperature == 0.1
    assert eff.max_retries == 5


def test_set_customization_context_excludes_round_trip(session):
    settings_service.set_customization(
        session, "scene_agent", context_excludes=["style", "story"], settings=_settings()
    )
    skills.clear_overrides()
    settings_service.load_overrides(session)
    assert skills.context_excludes("scene_agent") == {"style", "story"}


def test_customization_preserves_provider_override(session):
    s = _settings()
    settings_service.set_override(session, "script_agent", "minimax", "MiniMax-M2", s)
    settings_service.set_customization(
        session, "script_agent", system_prompt="Hi.", settings=s
    )
    eff = settings_service.effective_skill(session, "script_agent")
    assert eff.model == "MiniMax-M2"  # provider override survives
    assert eff.system_prompt == "Hi."


def test_clearing_provider_keeps_prompt_customization(session):
    s = _settings()
    settings_service.set_customization(
        session, "script_agent", system_prompt="Keep me.", settings=s
    )
    settings_service.set_override(session, "script_agent", "minimax", "MiniMax-M2", s)
    settings_service.set_override(session, "script_agent", None, None, s)  # clear routing
    eff = settings_service.effective_skill(session, "script_agent")
    assert eff.system_prompt == "Keep me."  # row not deleted
    base = skills.get_skill("script_agent")
    assert eff.provider == base.provider


# ------------------------------------------------------------- validation
def test_set_customization_rejects_unknown_placeholder(session):
    with pytest.raises(ValidationFailedError):
        settings_service.set_customization(
            session, "script_agent", system_prompt="hi {oops}", settings=_settings()
        )


def test_set_customization_rejects_malformed_braces(session):
    with pytest.raises(ValidationFailedError):
        settings_service.set_customization(
            session, "script_agent", system_prompt="a lone { brace", settings=_settings()
        )


def test_set_customization_accepts_plain_text(session):
    out = settings_service.set_customization(
        session, "script_agent", system_prompt="Plain rules, no braces.", settings=_settings()
    )
    assert out["system_prompt"] == "Plain rules, no braces."


def test_set_customization_clamps_temperature(session):
    settings_service.set_customization(
        session, "script_agent", temperature=9.0, settings=_settings()
    )
    assert settings_service.effective_skill(session, "script_agent").temperature == 2.0


def test_set_customization_clamps_retries(session):
    settings_service.set_customization(
        session, "script_agent", max_retries=99, settings=_settings()
    )
    assert settings_service.effective_skill(session, "script_agent").max_retries == 5


def test_set_customization_rejects_unknown_context_key(session):
    with pytest.raises(ValidationFailedError):
        settings_service.set_customization(
            session, "script_agent", context_excludes=["nonsense"], settings=_settings()
        )


def test_set_customization_rejects_required_context_key(session):
    # `idea` is required for script_agent — it cannot be excluded.
    with pytest.raises(ValidationFailedError):
        settings_service.set_customization(
            session, "script_agent", context_excludes=["idea"], settings=_settings()
        )


def test_set_customization_rejects_unknown_agent(session):
    with pytest.raises(NotFoundError):
        settings_service.set_customization(
            session, "nope_agent", system_prompt="x", settings=_settings()
        )


# ----------------------------------------------------------------- reset
def test_reset_agent_restores_defaults(session):
    s = _settings()
    settings_service.set_customization(
        session, "script_agent", system_prompt="custom", temperature=0.1, settings=s
    )
    settings_service.set_override(session, "script_agent", "minimax", "MiniMax-M2", s)
    settings_service.reset_agent(session, "script_agent", settings=s)
    eff = settings_service.effective_skill(session, "script_agent")
    base = skills.get_skill("script_agent")
    assert eff.system_prompt == base.system_prompt
    assert eff.temperature == base.temperature
    assert eff.provider == base.provider
    assert "script_agent" not in settings_service.get_overrides(session)


# ------------------------------------------------------------ detail view
def test_agent_detail_shape(session):
    detail = settings_service.agent_detail(session, "scene_agent", settings=_settings())
    assert detail["agent"] == "scene_agent"
    assert detail["default_prompt"] == skills.get_skill("scene_agent").system_prompt
    assert detail["system_prompt"] is None  # no override yet
    assert detail["required_placeholders"] == []
    assert isinstance(detail["context_sources"], list)
    keys = {c["key"] for c in detail["context_sources"]}
    assert "style" in keys and "story" in keys
    # required sources are flagged
    bibles = next(c for c in detail["context_sources"] if c["key"] == "character_bibles")
    assert bibles["required"] is True
    assert all(c["enabled"] for c in detail["context_sources"])
    assert detail["customized"] is False


def test_agent_detail_reflects_excludes(session):
    settings_service.set_customization(
        session, "scene_agent", context_excludes=["style"], settings=_settings()
    )
    detail = settings_service.agent_detail(session, "scene_agent", settings=_settings())
    style = next(c for c in detail["context_sources"] if c["key"] == "style")
    assert style["enabled"] is False
    assert detail["customized"] is True
