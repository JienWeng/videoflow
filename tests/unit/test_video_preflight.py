from app.providers.capabilities import capabilities_for, validate_render_capabilities
from app.providers.model_ids import H3_REFERENCE_TO_VIDEO, H3_TEXT_TO_VIDEO
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool
from app.services.video_preflight_service import video_preflight
from app.services import settings_service
from app.config import Settings


def test_h3_text_to_video_rejects_reference_images():
    capabilities = capabilities_for("atlascloud", H3_TEXT_TO_VIDEO)
    errors = validate_render_capabilities(
        capabilities,
        duration=8,
        aspect_ratio="9:16",
        reference_count=1,
        has_video_reference=False,
    )
    assert errors == ["at most 0 image references are supported"]


def test_h3_reference_to_video_requires_reference_material():
    capabilities = capabilities_for("atlascloud", H3_REFERENCE_TO_VIDEO)
    missing = validate_render_capabilities(
        capabilities,
        duration=8,
        aspect_ratio="9:16",
        reference_count=0,
        has_video_reference=False,
    )
    valid = validate_render_capabilities(
        capabilities,
        duration=8,
        aspect_ratio="9:16",
        reference_count=1,
        has_video_reference=False,
    )
    valid_video_reference = validate_render_capabilities(
        capabilities,
        duration=8,
        aspect_ratio="9:16",
        reference_count=0,
        has_video_reference=True,
    )
    assert missing == ["at least 1 reference item is required"]
    assert valid == []
    assert valid_video_reference == []
    assert capabilities.supports_video_reference is True


def test_unknown_model_is_unverified_in_preflight_capabilities():
    capabilities = capabilities_for("openrouter", "custom/unknown-model")
    assert capabilities.metadata["verified"] is False


def test_preflight_describes_h3_reference_route():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        result = video_preflight(session)
    assert result["routes"]["image"]["scope"] == "storyboards"
    assert result["routes"]["character_and_prop_images"]["provider"] == "atlascloud"
    assert result["routes"]["video"]["model"] == H3_REFERENCE_TO_VIDEO
    assert result["routes"]["video"]["max_reference_images"] == 7
    assert result["routes"]["video"]["min_reference_count"] == 1
    assert result["routes"]["video"]["resolution"] == "768P"
    assert result["routes"]["video"]["min_duration"] == 4
    assert result["routes"]["video"]["max_duration"] == 15
    assert result["routes"]["video"]["supports_generated_audio"] is True
    assert result["conversation_mode"] == "dialogue"


def test_preflight_flags_unsupported_h3_resolution(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    settings = Settings(_env_file=None, ATLAS_VIDEO_RESOLUTION="360P")
    monkeypatch.setattr(
        "app.services.video_preflight_service.get_settings", lambda: settings
    )
    with Session(engine) as session:
        result = video_preflight(session)
    assert any(
        "ATLAS_VIDEO_RESOLUTION" in item["reason"]
        for item in result["missing"]
    )


def test_preflight_accepts_h3_developer_text_route_at_480p(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    settings = Settings(_env_file=None, ATLAS_VIDEO_RESOLUTION="480P")
    monkeypatch.setattr(
        "app.services.video_preflight_service.get_settings", lambda: settings
    )
    with Session(engine) as session:
        settings_service.set_app_setting(session, "video_model", H3_TEXT_TO_VIDEO)
        result = video_preflight(session)
    route = result["routes"]["video"]
    assert route["model"] == H3_TEXT_TO_VIDEO
    assert route["resolution"] == "480P"
    assert route["max_reference_images"] == 0
    assert route["supports_generated_audio"] is True
    assert not any("ATLAS_VIDEO_RESOLUTION" in item["reason"] for item in result["missing"])


def test_preflight_uses_selected_preset_until_project_style_exists():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        result = video_preflight(session, style_choice="cinematic")
    assert result["effective_style"] == "Cinematic"
    assert result["has_project_style"] is False


def test_preflight_follows_selected_video_provider_and_model():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        settings_service.set_app_setting(session, "default_video_provider", "openrouter")
        settings_service.set_app_setting(session, "video_model", "google/veo-3.1-lite")
        result = video_preflight(session)
    assert result["routes"]["video"]["provider"] == "openrouter"
    assert result["routes"]["video"]["model"] == "google/veo-3.1-lite"
    assert result["routes"]["video"]["max_reference_images"] == 2
    assert result["routes"]["video"]["verified"] is True
