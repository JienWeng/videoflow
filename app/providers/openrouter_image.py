"""OpenRouter dedicated Images API adapter."""

from __future__ import annotations

from app.config import get_settings
from app.providers.openrouter_client import OpenRouterClient
from app.providers.base import PollResult, normalise_status


class OpenRouterImageProvider:
    name = "openrouter_image"

    def __init__(self, client: OpenRouterClient | None = None) -> None:
        self._client = client or OpenRouterClient()
        self._settings = get_settings()
        self._results: dict[str, dict] = {}

    async def build_payload(self, *, prompt: str, n: int = 1, size: str = "1024x1024") -> dict:
        return {"model": self._settings.openrouter_image_model, "prompt": prompt, "n": n, "size": size}

    async def build_reference_payload(self, *, prompt: str, images: list[str], aspect_ratio: str = "1:1") -> dict:
        return {
            "model": self._settings.openrouter_image_model,
            "prompt": prompt,
            "n": 1,
            "aspect_ratio": aspect_ratio,
            "input_references": [{"type": "image_url", "image_url": {"url": url}} for url in images],
        }

    async def submit(self, payload: dict) -> str:
        response = await self._client.create_image(payload)
        job_id = f"image-{id(response)}"
        self._results[job_id] = response
        return job_id

    async def poll(self, job_id: str) -> PollResult:
        response = self._results.pop(job_id, {})
        data = response.get("data") if isinstance(response, dict) else None
        item = data[0] if isinstance(data, list) and data else {}
        encoded = item.get("b64_json") if isinstance(item, dict) else None
        urls = [f"data:image/png;base64,{encoded}"] if encoded else []
        return PollResult(status="succeeded" if urls else "failed", output_urls=urls, error=None if urls else "missing image data", raw=response)
