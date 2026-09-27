from app.providers.capabilities import capabilities_for, validate_render_capabilities
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool
from app.services.video_preflight_service import video_preflight
from app.services import settings_service


def test_h3_preflight_capabilities_reject_reference_images():
    capabilities = capabilities_for("atlascloud", "minimax/h3-developer/text-to-video")
    errors = validate_render_capabilities(
        capabilities,
        duration=8,
        aspect_ratio="9:16",
        reference_count=1,
        has_video_reference=False,
    )
    assert errors == ["at most 0 image references are supported"]


def test_unknown_model_is_unverified_in_preflight_capabilities():
    capabilities = capabilities_for("openrouter", "custom/unknown-model")
    assert capabilities.metadata["verified"] is False


def test_preflight_describes_h3_without_image_inputs():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        result = video_preflight(session)
    assert result["routes"]["image"]["scope"] == "storyboards"
    assert result["routes"]["character_and_prop_images"]["provider"] == "atlascloud"
    assert result["routes"]["video"]["max_reference_images"] == 0
    assert result["conversation_mode"] == "dialogue"


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
