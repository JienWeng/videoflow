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


class AtlasCloudVideoProvider:
    name = "atlascloud_video"

    def __init__(self, client: AtlasCloudClient | None = None) -> None:
        self._client = client or get_atlas_client()
        self._settings = get_settings()

    async def build_payload(self, spec: RenderSpec, resolver: AssetUrlResolver) -> dict:
        images = await resolver.resolve(spec.all_reference_image_asset_ids)
        if not images:
            raise ValidationFailedError(
                "reference-to-video requires at least one reference image"
            )

        video_url = None
        if spec.video_asset_id:
            video_url = await resolver.resolve_one(spec.video_asset_id)

        payload: dict = {
            "model": spec.model or self._settings.atlas_video_model,
            "aspect_ratio": spec.aspect_ratio,
            "duration": max(3, min(spec.duration, 15)),
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
                payload["multi_prompt"] = [
                    {"prompt": s.prompt, "duration": s.duration}
                    for s in spec.multi_prompt
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
