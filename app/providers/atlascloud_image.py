"""AtlasCloud image provider — ERNIE text-to-image."""

from __future__ import annotations

from app.config import get_settings
from app.providers.atlascloud_client import (
    AtlasCloudClient,
    extract_outputs,
    get_atlas_client,
)
from app.providers.base import PollResult, normalise_status


class AtlasCloudImageProvider:
    name = "atlascloud_image"

    def __init__(self, client: AtlasCloudClient | None = None) -> None:
        self._client = client or get_atlas_client()
        self._settings = get_settings()
        self._sync_results: dict[str, PollResult] = {}

    async def build_payload(
        self, *, prompt: str, n: int = 1, size: str = "1024x1024"
    ) -> dict:
        return {
            "model": self._settings.atlas_image_model,
            "prompt": prompt,
            "size": size,
            "n": n,
            "seed": -1,
            "use_pe": True,
            "num_inference_steps": 8,
            "guidance_scale": 1,
            # Sync on purpose: AtlasCloud's async ERNIE dispatch fails upstream
            # ("failed to parse upstream response"), confirmed live 2026-06-10.
            "enable_sync_mode": True,
            "enable_base64_output": False,
        }

    async def build_reference_payload(
        self, *, prompt: str, images: list[str], aspect_ratio: str = "1:1"
    ) -> dict:
        """Image generation guided by reference images (character sheets) via the
        edit model — nano-banana-2/edit contract: prompt + images[] (max 10) +
        aspect_ratio. Sync mode for the same reason as text-to-image."""
        return {
            "model": self._settings.atlas_image_ref_model,
            "prompt": prompt,
            "images": images[:10],
            "aspect_ratio": aspect_ratio,
            "enable_sync_mode": True,
            "enable_base64_output": False,
        }

    async def submit(self, payload: dict) -> str:
        data = await self._client.generate_image(payload)
        job_id = data["id"]
        status = normalise_status(data.get("status"))
        if status in ("succeeded", "failed"):
            # Sync mode finished in-request; serve it from cache, never poll.
            self._sync_results[job_id] = PollResult(
                status=status,
                output_urls=extract_outputs(data) if status == "succeeded" else [],
                error=data.get("error") or None,
                raw=data,
            )
        return job_id

    async def poll(self, job_id: str) -> PollResult:
        if job_id in self._sync_results:
            return self._sync_results[job_id]
        data = await self._client.get_prediction(job_id)
        status = normalise_status(data.get("status"))
        return PollResult(
            status=status,
            output_urls=extract_outputs(data) if status == "succeeded" else [],
            error=data.get("error"),
            raw=data,
        )
