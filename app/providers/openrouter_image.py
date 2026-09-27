"""OpenRouter dedicated Images API adapter."""

from __future__ import annotations

from uuid import uuid4

from app.config import get_settings
from app.providers.openrouter_client import OpenRouterClient
from app.providers.base import PollResult, normalise_status


class OpenRouterImageProvider:
    name = "openrouter_image"

    def __init__(self, client: OpenRouterClient | None = None) -> None:
        self._client = client or OpenRouterClient()
        self._settings = get_settings()
        self.default_model = self._settings.openrouter_image_model
        self._results: dict[str, dict] = {}

    async def build_payload(self, *, prompt: str, n: int = 1, size: str = "1024x1024", model: str | None = None) -> dict:
        return {"model": model or self.default_model, "prompt": prompt, "n": n, "size": size}

    async def build_reference_payload(self, *, prompt: str, images: list[str], aspect_ratio: str = "1:1", model: str | None = None) -> dict:
        return {
            "model": model or self.default_model,
            "prompt": prompt,
            "n": 1,
            "aspect_ratio": aspect_ratio,
            "input_references": [{"type": "image_url", "image_url": {"url": url}} for url in images],
        }

    async def submit(self, payload: dict) -> str:
        response = await self._client.create_image(payload)
        job_id = f"image-{uuid4().hex}"
        self._results[job_id] = response
        return job_id

    async def poll(self, job_id: str) -> PollResult:
        response = self._results.get(job_id, {})
        data = response.get("data") if isinstance(response, dict) else None
        urls = []
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            encoded = item.get("b64_json")
            if encoded:
                mime = item.get("media_type") or item.get("mime_type") or "image/png"
                urls.append(f"data:{mime};base64,{encoded}")
            elif item.get("url"):
                urls.append(item["url"])
        return PollResult(status="succeeded" if urls else "failed", output_urls=urls, error=None if urls else "missing image data", raw=response)
