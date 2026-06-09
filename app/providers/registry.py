"""Provider lookup. Video resolves only to AtlasCloud (Kling o3)."""

from __future__ import annotations

from app.errors import UnsupportedProviderError
from app.providers.atlascloud_image import AtlasCloudImageProvider
from app.providers.atlascloud_video import AtlasCloudVideoProvider
from app.schemas import RenderSpec


def get_video_provider(spec: RenderSpec) -> AtlasCloudVideoProvider:
    if spec.provider != "atlascloud":
        raise UnsupportedProviderError(
            f"provider '{spec.provider}' is not supported; only 'atlascloud'"
        )
    return AtlasCloudVideoProvider()


def get_image_provider() -> AtlasCloudImageProvider:
    return AtlasCloudImageProvider()
