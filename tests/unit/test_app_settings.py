"""Unit tests for the app-settings resolver, provider secrets, and relaxed
model validation in settings_service."""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.config import Settings
from app.errors import ValidationFailedError
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


# ---------------------------------------------------------------- app settings

def test_resolve_falls_back_to_config_default(session):
    s = _settings(DEFAULT_ASPECT_RATIO="9:16")
    assert settings_service.resolve(session, "default_aspect_ratio", settings=s) == "9:16"


def test_set_and_get_global_app_setting(session):
    settings_service.set_app_setting(session, "default_aspect_ratio", "16:9")
    got = settings_service.get_app_setting(session, "default_aspect_ratio")
    assert got == "16:9"


def test_resolve_overlays_global_over_config(session):
    s = _settings(DEFAULT_ASPECT_RATIO="9:16")
    settings_service.set_app_setting(session, "default_aspect_ratio", "1:1")
    assert settings_service.resolve(session, "default_aspect_ratio", settings=s) == "1:1"


def test_resolve_project_override_beats_global(session):
    s = _settings(DEFAULT_ASPECT_RATIO="9:16")
    settings_service.set_app_setting(session, "default_aspect_ratio", "1:1")
    settings_service.set_app_setting(
        session, "default_aspect_ratio", "16:9", scope="project", project_id="p1"
    )
    # No project context -> global wins.
    assert settings_service.resolve(session, "default_aspect_ratio", settings=s) == "1:1"
    # Project context -> project override wins.
    assert (
        settings_service.resolve(
            session, "default_aspect_ratio", project_id="p1", settings=s
        )
        == "16:9"
    )


def test_resolve_unknown_key_returns_default_arg(session):
    assert settings_service.resolve(session, "no_such_key", default=42) == 42


def test_app_settings_view_has_all_keys(session):
    s = _settings()
    view = settings_service.app_settings_view(session, settings=s)
    for k in settings_service.APP_SETTING_KEYS:
        assert k in view


def test_set_app_setting_rejects_unknown_key(session):
    with pytest.raises(ValidationFailedError):
        settings_service.set_app_setting(session, "totally_bogus", "x")


def test_value_types_round_trip(session):
    settings_service.set_app_setting(session, "max_video_refs", 5)
    settings_service.set_app_setting(session, "render_negatives", ["blurry", "ugly"])
    assert settings_service.get_app_setting(session, "max_video_refs") == 5
    assert settings_service.get_app_setting(session, "render_negatives") == [
        "blurry",
        "ugly",
    ]


# ------------------------------------------------------------ provider secrets

def test_set_and_get_provider_config_masks_key(session):
    settings_service.set_provider_config(session, "openai", api_key="sk-supersecret123")
    cfg = settings_service.get_provider_config(session, "openai")
    assert cfg["configured"] is True
    assert "supersecret" not in cfg["masked_key"]
    assert cfg["masked_key"].endswith("123")
    # Raw key never returned.
    assert "api_key" not in cfg


def test_provider_secret_stored_obfuscated_not_plaintext(session):
    from app.models.setting import ProviderSecret
    from sqlmodel import select

    settings_service.set_provider_config(session, "openai", api_key="sk-plaintextkey")
    row = session.exec(
        select(ProviderSecret).where(ProviderSecret.provider == "openai")
    ).first()
    assert row is not None
    assert row.api_key != "sk-plaintextkey"  # obfuscated at rest


def test_is_configured_reads_db_over_env(session):
    s = _settings(OPENAI_API_KEY="")  # env not configured
    assert settings_service.is_configured("openai", s, session=session) is False
    settings_service.set_provider_config(session, "openai", api_key="sk-fromdb")
    assert settings_service.is_configured("openai", s, session=session) is True


def test_set_provider_config_clear_key(session):
    settings_service.set_provider_config(session, "openai", api_key="sk-x")
    assert settings_service.get_provider_config(session, "openai")["configured"] is True
    settings_service.set_provider_config(session, "openai", api_key="")
    assert settings_service.get_provider_config(session, "openai")["configured"] is False


def test_set_provider_config_base_url_only(session):
    settings_service.set_provider_config(session, "openai", api_key="sk-x")
    settings_service.set_provider_config(
        session, "openai", base_url="https://custom.example/v1"
    )
    cfg = settings_service.get_provider_config(session, "openai")
    assert cfg["base_url"] == "https://custom.example/v1"
    # Key preserved when only base_url updated.
    assert cfg["configured"] is True


# ------------------------------------------------ relaxed model validation

def test_set_override_accepts_custom_model_for_configured_provider(session):
    s = _settings()
    # A model NOT in the curated list, but provider configured -> now accepted.
    out = settings_service.set_override(
        session, "script_agent", "minimax", "MiniMax-Some-New-Model", s
    )
    assert out["model"] == "MiniMax-Some-New-Model"


def test_set_override_rejects_empty_model(session):
    s = _settings()
    with pytest.raises(ValidationFailedError):
        settings_service.set_override(session, "script_agent", "minimax", "", s)


def test_set_override_still_rejects_unconfigured_provider(session):
    s = _settings()
    with pytest.raises(ValidationFailedError):
        settings_service.set_override(
            session, "script_agent", "openai", "gpt-4o", s
        )


def test_set_override_uses_db_provider_secret_for_configured_check(session):
    # openai not in env, but a DB secret makes it configured -> override allowed.
    s = _settings(OPENAI_API_KEY="")
    settings_service.set_provider_config(session, "openai", api_key="sk-db")
    out = settings_service.set_override(
        session, "script_agent", "openai", "gpt-4o", s
    )
    assert out["provider"] == "openai"


# ------------------------------------------------------ catalog reports custom

def test_available_providers_reports_allow_custom_and_db_config(session):
    s = _settings(OPENAI_API_KEY="")
    settings_service.set_provider_config(session, "openai", api_key="sk-db")
    cat = settings_service.available_providers(s, session=session)
    by = {c["name"]: c for c in cat}
    assert by["openai"]["configured"] is True  # from DB
    assert by["openai"]["allow_custom"] is True
    assert "suggested_models" in by["openai"]
