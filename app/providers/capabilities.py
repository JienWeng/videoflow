"""Provider capability declarations and deterministic render validation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderCapabilities:
    provider: str
    modality: str = "video"
    min_duration: int = 4
    max_duration: int = 15
    aspect_ratios: frozenset[str] = frozenset({"16:9", "9:16", "1:1"})
    max_reference_images: int = 0
    supports_video_reference: bool = False
    supports_frame_images: bool = False
    metadata: dict[str, object] = field(default_factory=dict)


def capabilities_for(provider: str, model: str = "") -> ProviderCapabilities:
    if provider == "atlascloud":
        verified = model in {"minimax/h3-developer/text-to-video"}
        return ProviderCapabilities(
            provider=provider,
            max_reference_images=0,
            metadata={"model": model, "verified": verified},
        )
    if provider == "openrouter":
        verified = model in {
            "google/veo-3.1-lite",
            "google/veo-3.1-fast",
            "kwaivgi/kling-v3.0-pro",
        }
        max_duration = 8 if any(x in model.lower() for x in ("veo", "kling")) else 15
        return ProviderCapabilities(
            provider=provider,
            max_duration=max_duration,
            max_reference_images=2,
            supports_frame_images=True,
            metadata={"model": model, "verified": verified},
        )
    raise ValueError(f"unsupported media provider: {provider}")


def validate_render_capabilities(
    capabilities: ProviderCapabilities,
    *,
    duration: int,
    aspect_ratio: str,
    reference_count: int,
    has_video_reference: bool,
) -> list[str]:
    errors: list[str] = []
    if not capabilities.min_duration <= duration <= capabilities.max_duration:
        errors.append(f"duration must be between {capabilities.min_duration} and {capabilities.max_duration} seconds")
    if aspect_ratio not in capabilities.aspect_ratios:
        errors.append(f"aspect ratio '{aspect_ratio}' is not supported")
    if reference_count > capabilities.max_reference_images:
        errors.append(f"at most {capabilities.max_reference_images} image references are supported")
    if has_video_reference and not capabilities.supports_video_reference:
        errors.append("video references are not supported by this provider/model")
    return errors
