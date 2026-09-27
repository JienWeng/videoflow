"""Provider lookup. Video resolves only to AtlasCloud."""

from __future__ import annotations

from app.errors import UnsupportedProviderError
from app.providers.atlascloud_image import AtlasCloudImageProvider
from app.providers.atlascloud_video import AtlasCloudVideoProvider
from app.providers.openrouter_video import OpenRouterVideoProvider
from app.providers.openrouter_image import OpenRouterImageProvider
from app.schemas import RenderSpec


def get_video_provider(spec: RenderSpec):
    if spec.provider == "atlascloud":
        return AtlasCloudVideoProvider()
    if spec.provider == "openrouter":
        return OpenRouterVideoProvider()
    raise UnsupportedProviderError(f"provider '{spec.provider}' is not supported")


def get_image_provider(provider: str = "atlascloud"):
    if provider == "openrouter":
        return OpenRouterImageProvider()
    return AtlasCloudImageProvider()


def get_image_provider_for_session(session, project_id: str | None = None, *, atlas_client=None):
    """Select the configured image provider and expose its resolved model id."""
    from app.services import settings_service
    from app.providers.openrouter_image import OpenRouterImageProvider

    provider_name = settings_service.resolve(
        session, "default_image_provider", default="atlascloud", project_id=project_id
    )
    if provider_name == "openrouter":
        provider = OpenRouterImageProvider()
    else:
        from app.providers.atlascloud_client import get_atlas_client
        from app.providers.atlascloud_image import AtlasCloudImageProvider
        provider = AtlasCloudImageProvider(atlas_client or get_atlas_client(), session=session)
    if isinstance(provider, OpenRouterImageProvider):
        provider.default_model = settings_service.resolve(
            session, "image_model", default=None, project_id=project_id
        )
    return provider


def get_asset_resolver(session, provider_name: str, *, atlas_client=None):
    from app.providers.url_resolver import AtlasCloudUploadResolver, OpenRouterAssetResolver

    if provider_name in {"openrouter", "openrouter_image"}:
        return OpenRouterAssetResolver(session)
    from app.providers.atlascloud_client import get_atlas_client
    return AtlasCloudUploadResolver(session, atlas_client or get_atlas_client())
