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
