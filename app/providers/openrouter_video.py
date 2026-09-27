"""OpenRouter asynchronous video-generation adapter."""

from __future__ import annotations

from app.config import get_settings
from app.providers.base import PollResult, normalise_status
from app.providers.capabilities import capabilities_for, validate_render_capabilities
from app.providers.openrouter_client import OpenRouterClient
from app.providers.url_resolver import AssetUrlResolver
from app.schemas import RenderSpec


class OpenRouterVideoProvider:
    name = "openrouter_video"

    def __init__(self, client: OpenRouterClient | None = None) -> None:
        self._client = client or OpenRouterClient()
        self._settings = get_settings()

    async def build_payload(self, spec: RenderSpec, resolver: AssetUrlResolver) -> dict:
        model = spec.model or self._settings.openrouter_video_model
        caps = capabilities_for("openrouter", model)
        refs = await resolver.resolve(spec.all_reference_image_asset_ids)
        errors = validate_render_capabilities(caps, duration=spec.duration, aspect_ratio=spec.aspect_ratio, reference_count=len(refs), has_video_reference=bool(spec.video_asset_id))
        if errors:
            raise ValueError("; ".join(errors))
        payload = {"model": model, "prompt": spec.prompt, "aspect_ratio": spec.aspect_ratio, "duration": spec.duration, "resolution": "720p", "generate_audio": spec.sound}
        if refs:
            payload["frame_images"] = [
                {"type": "image_url", "image_url": {"url": url}, "frame_type": frame}
                for url, frame in zip(refs, ("first_frame", "last_frame"))
            ]
        return payload

    async def submit(self, payload: dict) -> str:
        response = await self._client.create_video(payload)
        job_id = response.get("id")
        if not job_id:
            raise ValueError(f"OpenRouter video response missing id: {response}")
        return job_id

    async def poll(self, job_id: str) -> PollResult:
        data = await self._client.get_video(job_id)
        status = normalise_status(data.get("status"))
        urls = data.get("unsigned_urls") or data.get("output") or []
        if isinstance(urls, str):
            urls = [urls]
        return PollResult(status=status, output_urls=list(urls) if status == "succeeded" else [], error=data.get("error"), raw=data)
