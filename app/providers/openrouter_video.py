"""OpenRouter asynchronous video-generation adapter."""

from __future__ import annotations

from app.config import get_settings
from app.providers.base import PollResult, normalise_status
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
        refs = await resolver.resolve(spec.all_reference_image_asset_ids)
        frame_ids = [aid for aid in (spec.first_frame_asset_id, spec.last_frame_asset_id) if aid]
        frames = await resolver.resolve(frame_ids) if frame_ids else []
        if spec.video_asset_id:
            raise ValueError("OpenRouter video generation does not accept video reference assets")
        models = await self._client.get_video_models()
        model_info = next((item for item in models if item.get("id") == model), None)
        if model_info is None:
            raise ValueError(f"OpenRouter video model '{model}' was not found in the video models catalog")
        durations = model_info.get("supported_durations") or []
        if durations and spec.duration not in durations:
            raise ValueError(f"duration {spec.duration}s is unsupported by {model}; supported durations: {durations}")
        aspects = model_info.get("supported_aspect_ratios") or []
        if aspects and spec.aspect_ratio not in aspects:
            raise ValueError(f"aspect ratio {spec.aspect_ratio} is unsupported by {model}; supported ratios: {aspects}")
        resolutions = model_info.get("supported_resolutions") or []
        resolution = "720p" if "720p" in resolutions else (resolutions[0] if resolutions else None)
        prompt = spec.prompt
        if spec.multi_shot and spec.multi_prompt:
            prompt += "\n\nShot sequence:\n" + "\n".join(
                f"Shot {i + 1} ({shot.duration}s): {shot.prompt}"
                for i, shot in enumerate(spec.multi_prompt)
            )
        payload = {"model": model, "prompt": prompt, "aspect_ratio": spec.aspect_ratio, "duration": spec.duration, "generate_audio": spec.sound}
        if resolution:
            payload["resolution"] = resolution
        if frames:
            payload["frame_images"] = [
                {"type": "image_url", "image_url": {"url": url}, "frame_type": frame}
                for url, frame in zip(
                    frames,
                    (["first_frame"] if spec.first_frame_asset_id else [])
                    + (["last_frame"] if spec.last_frame_asset_id else []),
                )
            ]
        elif refs:
            payload["input_references"] = [
                {"type": "image_url", "image_url": {"url": url}} for url in refs
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

    async def download_output(self, job_id: str, index: int = 0) -> tuple[bytes, str]:
        return await self._client.download_video(job_id, index)
