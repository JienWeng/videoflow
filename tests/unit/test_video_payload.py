"""Unit tests for RenderSpec -> Kling o3 payload mapping."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.errors import ValidationFailedError
from app.providers.atlascloud_video import AtlasCloudVideoProvider
from app.schemas import ReferenceImage, RenderSpec, StoryboardShot


class FakeResolver:
    """Maps asset_id -> a fake hosted URL; records call order."""

    def __init__(self):
        self.resolved: list[str] = []

    async def resolve(self, asset_ids):
        self.resolved.extend(asset_ids)
        return [f"https://static.atlascloud.ai/{a}.png" for a in asset_ids]

    async def resolve_one(self, asset_id):
        self.resolved.append(asset_id)
        return f"https://static.atlascloud.ai/{asset_id}.mp4"


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(
        "app.providers.atlascloud_video.get_settings",
        lambda: Settings(ATLASCLOUD_API_KEY="k", MINIMAX_API_KEY="k"),
    )
    # Avoid constructing a real HTTP client.
    return AtlasCloudVideoProvider(client=object())


async def test_single_shot_payload_with_named_refs(provider):
    spec = RenderSpec(
        scene_id="s1", shot_id="sh1", duration=5, aspect_ratio="9:16",
        prompt="@Kling Lipstick streaks across @Image",
        reference_images=[
            ReferenceImage(name="Kling Lipstick", asset_id="asset_a"),
            ReferenceImage(name="Image", asset_id="asset_b"),
        ],
    )
    payload = await provider.build_payload(spec, FakeResolver())

    assert payload["model"] == "kwaivgi/kling-video-o3-pro/reference-to-video"
    assert payload["aspect_ratio"] == "9:16"
    assert payload["duration"] == 5
    # Named references map, in @-token order, into images[].
    assert payload["images"] == [
        "https://static.atlascloud.ai/asset_a.png",
        "https://static.atlascloud.ai/asset_b.png",
    ]
    # Voice/sound on by default.
    assert payload["sound"] is True
    assert payload["keep_original_sound"] is True
    assert payload["multi_shot"] is False
    assert "multi_prompt" not in payload
    assert "video" not in payload


async def test_multi_shot_customize_payload(provider):
    spec = RenderSpec(
        scene_id="s1", duration=5, prompt="story",
        reference_images=[ReferenceImage(name="Image", asset_id="a")],
        multi_shot=True, shot_type="customize",
        multi_prompt=[
            StoryboardShot(prompt="color river streaks", duration=3),
            StoryboardShot(prompt="lipstick blooms on water", duration=2),
        ],
    )
    payload = await provider.build_payload(spec, FakeResolver())
    assert payload["multi_shot"] is True
    assert payload["shot_type"] == "customize"
    # Live API ret:1201 — "each entry in multi_prompt must have index and duration".
    assert payload["multi_prompt"] == [
        {"index": 1, "prompt": "color river streaks", "duration": 3},
        {"index": 2, "prompt": "lipstick blooms on water", "duration": 2},
    ]
    assert sum(s["duration"] for s in payload["multi_prompt"]) == payload["duration"]


async def test_reference_video_included(provider):
    spec = RenderSpec(
        scene_id="s1", duration=5, prompt="p",
        reference_images=[ReferenceImage(name="Image", asset_id="a")],
        video_asset_id="vid_1",
    )
    payload = await provider.build_payload(spec, FakeResolver())
    assert payload["video"] == "https://static.atlascloud.ai/vid_1.mp4"


async def test_missing_reference_images_rejected(provider):
    spec = RenderSpec(scene_id="s1", duration=5, prompt="p")
    with pytest.raises(ValidationFailedError):
        await provider.build_payload(spec, FakeResolver())
