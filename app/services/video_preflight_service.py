"""Local readiness checks for the guided Create flow."""

from __future__ import annotations

from sqlmodel import Session

from app.config import get_settings
from app.providers.capabilities import capabilities_for, validate_render_capabilities
from app.services import project_service, settings_service, style_service

CORE_AGENTS = ("script_agent", "scene_agent", "shot_agent", "asset_planner", "prompt_agent")


def video_preflight(
    session: Session,
    *,
    aspect_ratio: str = "9:16",
    style_choice: str = "2d-picture-book",
) -> dict:
    """Report configured generation routes without making provider requests."""
    settings = get_settings()
    project_id = project_service.active_project_id(session)
    app = settings_service.app_settings_view(session, project_id=project_id, settings=settings)
    agents = {agent["agent"]: agent for agent in settings_service.all_agents(session, settings)}

    missing = []
    for name in CORE_AGENTS:
        route = agents.get(name)
        if (
            not route
            or not route.get("model")
            or not settings_service.is_configured(route["provider"], settings, session)
        ):
            missing.append({"route": name, "setting": "/settings#providers", "reason": "Configure its text provider."})

    image_provider = app["default_image_provider"]
    video_provider = app["default_video_provider"]
    image_model = app["image_model"] or ""
    character_image_model = app["ref_image_model"] or ""
    for route, model in (
        ("image", image_model),
        ("character and prop images", character_image_model),
    ):
        if not model:
            missing.append({"route": route, "setting": "/settings#engines", "reason": f"Choose a model for {route}."})
    media_configured = {
        "atlascloud": settings_service.is_configured("atlas", settings, session),
        "openrouter": settings_service.is_configured("openrouter", settings, session),
    }
    for route, provider in (
        ("image", image_provider),
        ("character and prop images", "atlascloud"),
        ("video", video_provider),
    ):
        if not media_configured.get(provider):
            missing.append({
                "route": route,
                "setting": "/settings#providers",
                "reason": f"Configure {provider} credentials for {route} generation.",
            })

    video_model = app["video_model"] or ""
    if not video_model:
        missing.append({"route": "video", "setting": "/settings#engines", "reason": "Choose a video model."})
    capabilities = capabilities_for(video_provider, video_model)
    warnings = []
    image_models = {
        "atlascloud": {"openai/gpt-image-2/text-to-image", "google/nano-banana-2/edit"},
        "openrouter": {"openai/gpt-image-2"},
    }
    if image_model and image_model not in image_models.get(image_provider, set()):
        warnings.append({"route": "image", "reason": f"Model ID '{image_model}' is custom and unverified for {image_provider}."})
    if character_image_model and character_image_model not in image_models["atlascloud"]:
        warnings.append({"route": "character and prop images", "reason": f"Model ID '{character_image_model}' is custom and unverified for AtlasCloud."})
    if not capabilities.metadata["verified"]:
        warnings.append({
            "route": "video",
            "reason": f"Model ID '{video_model}' is custom and has not been verified by VideoFlow.",
        })
    compatibility = validate_render_capabilities(
        capabilities,
        duration=capabilities.min_duration,
        aspect_ratio=aspect_ratio,
        reference_count=0,
        has_video_reference=False,
    )
    if compatibility:
        missing.append({"route": "video", "setting": "/settings#engines", "reason": "; ".join(compatibility)})
    style = style_service.get_style(session)
    effective_style = style.name if style else (
        "Cinematic" if style_choice == "cinematic" else "2D picture book"
    )
    return {
        "ready": not missing,
        "missing": missing,
        "warnings": warnings,
        "routes": {
            "text": [agents[name] for name in CORE_AGENTS if name in agents],
            "image": {"provider": image_provider, "model": image_model, "scope": "storyboards"},
            "character_and_prop_images": {
                "provider": "atlascloud",
                "model": app["ref_image_model"],
            },
            "video": {
                "provider": video_provider,
                "model": video_model,
                "verified": capabilities.metadata["verified"],
                "max_reference_images": capabilities.max_reference_images,
                "supports_video_reference": capabilities.supports_video_reference,
                "max_duration": capabilities.max_duration,
                "aspect_ratios": sorted(capabilities.aspect_ratios),
            },
        },
        "effective_style": effective_style,
        "has_project_style": style is not None,
        "conversation_mode": "dialogue",
        "stages": ["story", "scenes", "shots", "dialogue", "visuals", "render"],
    }
