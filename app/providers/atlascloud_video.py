"""AtlasCloud video provider — MiniMax H3 Developer Reference-to-Video.

Maps stored image/video assets to the H3 `refers` field and preserves ordered
shot dialogue in one chronological prompt. Text-to-video remains available when
explicitly selected, but it does not receive reference assets.

The `max_video_refs` setting is an application upload/cost cap. AtlasCloud's
Reference-to-Video docs require at least one reference and don't publish an upper
limit.
"""

from __future__ import annotations

from app.config import get_settings
from app.errors import ProviderError
from app.providers.atlascloud_client import (
    AtlasCloudClient,
    extract_outputs,
    get_atlas_client,
)
from app.providers.base import PollResult, normalise_status
from app.providers.capabilities import (
    H3_STANDARD_RESOLUTIONS,
    capabilities_for,
)
from app.providers.model_ids import is_h3_reference_model
from app.providers.url_resolver import AssetUrlResolver
from app.schemas import RenderSpec

# ---------------------------------------------------------------------------
# H3 Developer video generation accepts 4-15 second clips, generated audio,
# and 480P, 768P, or 2K. Reference-to-Video needs at least one reference.
# ---------------------------------------------------------------------------
VIDEO_MIN_DURATION = 4
VIDEO_MAX_DURATION = 15
DEFAULT_VIDEO_MAX_REFS = 7
VIDEO_RESOLUTIONS = {"480P", "768P", "2K"}

CAPABILITIES: dict = {
    "min_duration_s": VIDEO_MIN_DURATION,
    "max_duration_s": VIDEO_MAX_DURATION,
    "default_reference_image_limit": DEFAULT_VIDEO_MAX_REFS,
    "required_reference_count": 1,
    "resolutions": sorted(VIDEO_RESOLUTIONS),
}


def clamp_duration(duration: int) -> int:
    """Clamp a requested duration into the provider's accepted range."""
    return max(VIDEO_MIN_DURATION, min(duration, VIDEO_MAX_DURATION))


class AtlasCloudVideoProvider:
    name = "atlascloud_video"

    def __init__(self, client: AtlasCloudClient | None = None) -> None:
        self._client = client or get_atlas_client()
        self._settings = get_settings()

    def _max_refs(self, resolver: AssetUrlResolver, scene_id: str) -> int:
        """Use the same project-aware image-reference cap as prompt selection."""
        session = getattr(resolver, "_session", None)
        if session is None:
            return self._settings.atlas_video_max_refs
        from app.models import Scene
        from app.services import settings_service

        scene = session.get(Scene, scene_id)
        return settings_service.resolve_video_reference_limit(
            session,
            project_id=scene.project_id if scene else None,
            settings=self._settings,
        )

    async def build_payload(self, spec: RenderSpec, resolver: AssetUrlResolver) -> dict:
        settings = self._settings
        prompt = spec.prompt.strip()
        if spec.multi_shot and spec.multi_prompt:
            beats = " ".join(
                f"Beat {i}: {shot.prompt.strip()}"
                for i, shot in enumerate(spec.multi_prompt, 1)
            )
            prompt = f"{prompt} Create one continuous, chronological video. {beats}"
        model = spec.model or self._settings.atlas_video_model
        resolution = settings.atlas_video_resolution.upper()
        allowed_resolutions = (
            capabilities_for("atlascloud", model).supported_resolutions
            or H3_STANDARD_RESOLUTIONS
        )
        if resolution not in allowed_resolutions:
            supported = " or ".join(sorted(allowed_resolutions))
            raise ProviderError(
                f"AtlasCloud model {model!r} resolution must be {supported}; "
                f"configured value is {settings.atlas_video_resolution!r}"
            )

        payload: dict = {
            "model": model,
            "ratio": spec.aspect_ratio,
            "duration": clamp_duration(spec.duration),
            "resolution": resolution,
            "prompt_expansion": settings.atlas_video_prompt_expansion,
        }
        if is_h3_reference_model(model):
            max_refs = max(1, self._max_refs(resolver, spec.scene_id))
            image_ids = spec.all_reference_image_asset_ids[:max_refs]
            image_urls = await resolver.resolve(image_ids) if image_ids else []
            refers = [{"url": url, "type": "image"} for url in image_urls]
            if spec.video_asset_id:
                video_url = await resolver.resolve_one(spec.video_asset_id)
                refers.append({"url": video_url, "type": "video"})
            if not refers:
                raise ProviderError(
                    "AtlasCloud H3 Reference-to-Video requires at least one image "
                    "or video reference"
                )
            payload["refers"] = refers
            named = {
                ref.asset_id: ref.name
                for ref in spec.reference_images
                if ref.asset_id in image_ids
            }
            labels = [
                f"Reference image {index}: {named[asset_id]}"
                for index, asset_id in enumerate(image_ids, 1)
                if named.get(asset_id)
            ]
            reference_context = (
                "Use the supplied reference materials to guide character identity, "
                "wardrobe, composition, palette, and scene continuity. "
            )
            if labels:
                reference_context += "Reference image order: " + "; ".join(labels) + ". "
            prompt = reference_context + prompt
        if capabilities_for("atlascloud", model).supports_generated_audio:
            prompt += (
                " Speak every written character dialogue line as clear, natural "
                "audible speech; preserve the exact words and speaker identities."
            )
        prompt = (
            f"{prompt} Maintain the same characters, wardrobe, location, lighting, "
            "and props across every beat. No new characters, no scene jumps, no "
            "subtitles, on-screen text, watermark, or random outfit changes."
        )
        payload["prompt"] = prompt
        return payload

    async def submit(self, payload: dict) -> str:
        return await self._client.generate_video(payload)

    async def poll(self, job_id: str) -> PollResult:
        data = await self._client.get_prediction(job_id)
        status = normalise_status(data.get("status"))
        return PollResult(
            status=status,
            output_urls=extract_outputs(data) if status == "succeeded" else [],
            error=data.get("error"),
            raw=data,
        )
