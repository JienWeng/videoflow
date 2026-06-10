"""Unit test locking the ERNIE text-to-image payload to the AtlasCloud reference."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.providers.atlascloud_image import AtlasCloudImageProvider


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(
        "app.providers.atlascloud_image.get_settings",
        lambda: Settings(ATLASCLOUD_API_KEY="k", MINIMAX_API_KEY="k"),
    )
    return AtlasCloudImageProvider(client=object())


async def test_payload_matches_atlascloud_reference(provider):
    payload = await provider.build_payload(prompt="cinematic night city", n=2, size="1024x1024")
    assert payload == {
        "model": "baidu/ERNIE-Image-Turbo/text-to-image",
        "prompt": "cinematic night city",
        "size": "1024x1024",
        "n": 2,
        "seed": -1,
        "use_pe": True,
        "num_inference_steps": 8,
        "guidance_scale": 1,
        # Sync mode on purpose: AtlasCloud's async ERNIE dispatch fails upstream
        # ("failed to parse upstream response"), confirmed live 2026-06-10.
        "enable_sync_mode": True,
        "enable_base64_output": False,
    }


async def test_reference_payload_targets_the_edit_model(provider):
    """分镜图 with character sheets: nano-banana-2/edit contract — prompt +
    images[] + aspect_ratio, sync mode (live API schema, fetched 2026-06-10)."""
    payload = await provider.build_reference_payload(
        prompt="storyboard grid",
        images=["https://x/char1.png", "https://x/char2.png"],
        aspect_ratio="9:16",
    )
    assert payload == {
        "model": "google/nano-banana-2/edit",
        "prompt": "storyboard grid",
        "images": ["https://x/char1.png", "https://x/char2.png"],
        "aspect_ratio": "9:16",
        "enable_sync_mode": True,
        "enable_base64_output": False,
    }


async def test_sync_completed_submit_is_returned_by_poll_without_http(provider):
    """When the sync response is already terminal, poll() must serve it from
    cache — the prediction endpoint is never hit (client is a dummy object)."""

    class SyncClient:
        async def generate_image(self, payload):
            return {"id": "p9", "status": "completed", "outputs": ["https://x/i.png"]}

    provider._client = SyncClient()
    payload = await provider.build_payload(prompt="x")
    job_id = await provider.submit(payload)
    assert job_id == "p9"
    result = await provider.poll(job_id)
    assert result.status == "succeeded"
    assert result.output_urls == ["https://x/i.png"]
