"""Unit tests for RenderSpec -> Kling o3 payload mapping."""

from __future__ import annotations

import pytest

from app.config import Settings
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

    assert payload["model"] == "minimax/h3-developer/text-to-video"
    assert payload["ratio"] == "9:16"
    assert payload["duration"] == 5
    assert payload["resolution"] == "480P"
    assert payload["prompt_expansion"] is False
    assert "images" not in payload
    assert "Kling Lipstick" in payload["prompt"]


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
    assert "Beat 1: color river streaks" in payload["prompt"]
    assert "Beat 2: lipstick blooms on water" in payload["prompt"]
    assert "chronological" in payload["prompt"]


async def test_reference_video_included(provider):
    spec = RenderSpec(
        scene_id="s1", duration=5, prompt="p",
        reference_images=[ReferenceImage(name="Image", asset_id="a")],
        video_asset_id="vid_1",
    )
    payload = await provider.build_payload(spec, FakeResolver())
    assert "video" not in payload


async def test_text_to_video_does_not_require_reference_images(provider):
    spec = RenderSpec(scene_id="s1", duration=5, prompt="p")
    payload = await provider.build_payload(spec, FakeResolver())
    assert payload["model"] == "minimax/h3-developer/text-to-video"


async def test_reference_images_are_not_sent_to_text_to_video(provider):
    spec = RenderSpec(
        scene_id="s1", duration=5, prompt="p",
        reference_images=[
            ReferenceImage(name=f"r{i}", asset_id=f"asset_{i}") for i in range(9)
        ],
    )
    payload = await provider.build_payload(spec, FakeResolver())
    assert "images" not in payload
