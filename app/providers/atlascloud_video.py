"""AtlasCloud video provider — MiniMax H3 Developer text-to-video.

Maps a RenderSpec to the H3 Developer text-to-video schema. Reference assets
are preserved in the prompt as continuity descriptions upstream; this model
does not accept the old Kling reference/multi-shot fields.

The render prompt carries named entities and ordered beats; the text-to-video
endpoint receives one controlled chronological prompt rather than unsupported
Kling reference/multi-shot fields.
"""

from __future__ import annotations

from app.config import get_settings
from app.providers.atlascloud_client import (
    AtlasCloudClient,
    extract_outputs,
    get_atlas_client,
)
from app.providers.base import PollResult, normalise_status
from app.providers.url_resolver import AssetUrlResolver
from app.schemas import RenderSpec

# ---------------------------------------------------------------------------
# Declared provider capabilities — H3 Developer text-to-video hard limits,
# consolidated here as module metadata instead of scattered magic numbers.
#   - duration: the live API accepts 4-15s; out-of-range values are clamped.
#   - max_reference_images remains exposed for compatibility with the existing
#     asset planner; H3 text-to-video itself does not receive images[].
# ---------------------------------------------------------------------------
VIDEO_MIN_DURATION = 4
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
        settings = self._settings
        prompt = spec.prompt.strip()
        if spec.multi_shot and spec.multi_prompt:
            beats = " ".join(
                f"Beat {i}: {shot.prompt.strip()}"
                for i, shot in enumerate(spec.multi_prompt, 1)
            )
            prompt = f"{prompt} Create one continuous, chronological video. {beats}"
        prompt = (
            f"{prompt} Maintain the same characters, wardrobe, location, lighting, "
            "and props across every beat. No new characters, no scene jumps, no "
            "subtitles, on-screen text, watermark, or random outfit changes."
        )
        payload: dict = {
            "model": spec.model or self._settings.atlas_video_model,
            "ratio": spec.aspect_ratio,
            "duration": clamp_duration(spec.duration),
            "resolution": settings.atlas_video_resolution,
            "prompt": prompt,
            "prompt_expansion": settings.atlas_video_prompt_expansion,
        }
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
