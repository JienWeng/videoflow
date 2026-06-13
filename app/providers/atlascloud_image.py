"""AtlasCloud image provider — ERNIE text-to-image."""

from __future__ import annotations

from sqlmodel import Session

from app.config import get_settings
from app.providers.atlascloud_client import (
    AtlasCloudClient,
    extract_outputs,
    get_atlas_client,
)
from app.providers.base import PollResult, normalise_status

# ---------------------------------------------------------------------------
# Declared provider capabilities + tunable image-gen params, consolidated here
# as module metadata. The reference (edit) model accepts at most 10 reference
# images; the generation params (steps/guidance/seed/size) are read through the
# settings resolver so quality/cost is tunable per-deployment WITHOUT changing
# the defaults (a fresh DB resolves to exactly these numbers).
# ---------------------------------------------------------------------------
STORYBOARD_IMAGE_CAP = 10
DEFAULT_NUM_INFERENCE_STEPS = 8
DEFAULT_GUIDANCE_SCALE = 1
DEFAULT_IMAGE_SIZE = "1024x1024"
DEFAULT_SEED = -1

CAPABILITIES: dict = {
    "max_reference_images": STORYBOARD_IMAGE_CAP,
    "default_num_inference_steps": DEFAULT_NUM_INFERENCE_STEPS,
    "default_guidance_scale": DEFAULT_GUIDANCE_SCALE,
    "default_size": DEFAULT_IMAGE_SIZE,
    "default_seed": DEFAULT_SEED,
}

# Settings-resolver keys for the tunable image-gen params (defaults above).
_PARAM_KEYS = {
    "num_inference_steps": ("image_num_inference_steps", DEFAULT_NUM_INFERENCE_STEPS),
    "guidance_scale": ("image_guidance_scale", DEFAULT_GUIDANCE_SCALE),
    "seed": ("image_seed", DEFAULT_SEED),
    "size": ("image_size", DEFAULT_IMAGE_SIZE),
}


class AtlasCloudImageProvider:
    name = "atlascloud_image"

    def __init__(
        self,
        client: AtlasCloudClient | None = None,
        session: Session | None = None,
    ) -> None:
        self._client = client or get_atlas_client()
        self._settings = get_settings()
        # Optional session: when wired, image-gen params + model id are read
        # through the settings resolver. Without it, config defaults apply —
        # identical behaviour to before.
        self._session = session
        self._sync_results: dict[str, PollResult] = {}

    def _resolve(self, key: str, default):
        """Resolve a setting value, preferring the DB store when a session is
        wired, else the supplied config default (behaviour unchanged by default)."""
        if self._session is None:
            return default
        from app.services import settings_service

        return settings_service.resolve(
            self._session, key, default=default, settings=self._settings
        )

    def _image_model(self) -> str:
        return self._resolve("image_model", self._settings.atlas_image_model)

    def _ref_image_model(self) -> str:
        return self._resolve("ref_image_model", self._settings.atlas_image_ref_model)

    def _param(self, name: str):
        key, default = _PARAM_KEYS[name]
        return self._resolve(key, default)

    async def build_payload(
        self, *, prompt: str, n: int = 1, size: str | None = None
    ) -> dict:
        return {
            "model": self._image_model(),
            "prompt": prompt,
            "size": size if size is not None else self._param("size"),
            "n": n,
            "seed": self._param("seed"),
            "use_pe": True,
            "num_inference_steps": self._param("num_inference_steps"),
            "guidance_scale": self._param("guidance_scale"),
            # Sync on purpose: AtlasCloud's async ERNIE dispatch fails upstream
            # ("failed to parse upstream response"), confirmed live 2026-06-10.
            "enable_sync_mode": True,
            "enable_base64_output": False,
        }

    async def build_reference_payload(
        self, *, prompt: str, images: list[str], aspect_ratio: str = "1:1"
    ) -> dict:
        """Image generation guided by reference images (character sheets) via the
        edit model — nano-banana-2/edit contract: prompt + images[] (max
        STORYBOARD_IMAGE_CAP) + aspect_ratio. Sync mode for the same reason as
        text-to-image."""
        return {
            "model": self._ref_image_model(),
            "prompt": prompt,
            "images": images[:STORYBOARD_IMAGE_CAP],
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
