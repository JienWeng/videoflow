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
            "num_inference_steps": 12,
            "guidance_scale": 1,
            "enable_sync_mode": False,
            "enable_base64_output": False,
        }

    async def submit(self, payload: dict) -> str:
        return await self._client.generate_image(payload)

    async def poll(self, job_id: str) -> PollResult:
        data = await self._client.get_prediction(job_id)
        status = normalise_status(data.get("status"))
        return PollResult(
            status=status,
            output_urls=extract_outputs(data) if status == "succeeded" else [],
            error=data.get("error"),
            raw=data,
        )
