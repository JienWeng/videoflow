"""AtlasCloud video provider — Kling o3-pro reference-to-video.

Maps a RenderSpec to the exact Kling input schema:
  model, aspect_ratio, duration(3-15), images[], video, prompt,
  sound, keep_original_sound, multi_shot, shot_type, multi_prompt[].

Multiple NAMED reference images resolve (in @-token order) into images[];
voice/sound flags pass through; multi-shot storyboards are validated by RenderSpec
itself (durations sum to total, each >= 1).
"""

from __future__ import annotations

from app.config import get_settings
from app.errors import ValidationFailedError
from app.providers.atlascloud_client import (
    AtlasCloudClient,
    extract_outputs,
    get_atlas_client,
)
from app.providers.base import PollResult, normalise_status
from app.providers.url_resolver import AssetUrlResolver
from app.schemas import RenderSpec

# ---------------------------------------------------------------------------
# Declared provider capabilities — Kling o3-pro reference-to-video hard limits,
# consolidated here as module metadata instead of scattered magic numbers.
#   - duration: the live API accepts 3-15s; out-of-range values are clamped.
#   - reference images: ret:1201 "max number is 7" above 7 (live-verified,
#     despite docs claiming 10). The effective cap is read from the settings
#     resolver (key 'max_video_refs'); this is the fallback default.
# ---------------------------------------------------------------------------
VIDEO_MIN_DURATION = 3
VIDEO_MAX_DURATION = 15
DEFAULT_VIDEO_MAX_REFS = 7

CAPABILITIES: dict = {
    "min_duration_s": VIDEO_MIN_DURATION,
    "max_duration_s": VIDEO_MAX_DURATION,
    "max_reference_images": DEFAULT_VIDEO_MAX_REFS,
}


def clamp_duration(duration: int) -> int:
    """Clamp a requested duration into the provider's accepted range."""
    return max(VIDEO_MIN_DURATION, min(duration, VIDEO_MAX_DURATION))


class AtlasCloudVideoProvider:
    name = "atlascloud_video"

    def __init__(self, client: AtlasCloudClient | None = None) -> None:
        self._client = client or get_atlas_client()
        self._settings = get_settings()

    def _max_refs(self, resolver: AssetUrlResolver) -> int:
        """Effective reference-image cap: read from the settings resolver when a
        session is reachable (the real resolver carries one), else the config /
        metadata default. Behaviour is identical by default — a fresh DB resolves
        to atlas_video_max_refs (7)."""
        session = getattr(resolver, "_session", None)
        if session is None:
            return self._settings.atlas_video_max_refs
        from app.services import settings_service

        return settings_service.resolve(
            session,
            "max_video_refs",
            default=self._settings.atlas_video_max_refs,
            settings=self._settings,
        )

    async def build_payload(self, spec: RenderSpec, resolver: AssetUrlResolver) -> dict:
        images = await resolver.resolve(spec.all_reference_image_asset_ids)
        if not images:
            raise ValidationFailedError(
                "reference-to-video requires at least one reference image"
            )
        # Belt-and-braces: the live API rejects more images than this with
        # ret:1201; the upstream priority cap should already hold the limit.
        images = images[: self._max_refs(resolver)]

        video_url = None
        if spec.video_asset_id:
            video_url = await resolver.resolve_one(spec.video_asset_id)

        payload: dict = {
            "model": spec.model or self._settings.atlas_video_model,
            "aspect_ratio": spec.aspect_ratio,
            "duration": clamp_duration(spec.duration),
            "prompt": spec.prompt,
            "images": images,
            "sound": spec.sound,
            "keep_original_sound": spec.keep_original_sound,
            "multi_shot": spec.multi_shot,
        }
        if video_url:
            payload["video"] = video_url
        if spec.multi_shot:
            payload["shot_type"] = spec.shot_type
            if spec.shot_type == "customize":
                # Live API requires index on every entry (ret:1201), 1-based.
                payload["multi_prompt"] = [
                    {"index": i + 1, "prompt": s.prompt, "duration": s.duration}
                    for i, s in enumerate(spec.multi_prompt)
                ]
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
