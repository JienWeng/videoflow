"""Unit tests for RenderSpec -> AtlasCloud H3 video payload mapping."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.errors import ProviderError
from app.providers.atlascloud_video import AtlasCloudVideoProvider
from app.providers.model_ids import H3_REFERENCE_TO_VIDEO, H3_TEXT_TO_VIDEO
from app.schemas import ReferenceImage, RenderSpec, StoryboardShot


class FakeResolver:
    """Maps asset ids to hosted URLs and records which assets are uploaded."""

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
    return AtlasCloudVideoProvider(client=object())


async def test_reference_to_video_payload_sends_storyboard_and_character_urls(provider):
    resolver = FakeResolver()
    spec = RenderSpec(
        scene_id="s1", shot_id="sh1", duration=5, aspect_ratio="9:16",
        prompt="@Mira walks through the garden",
        reference_images=[
            ReferenceImage(name="Mira", asset_id="character_mira"),
            ReferenceImage(name="Storyboard", asset_id="storyboard_1"),
        ],
    )

    payload = await provider.build_payload(spec, resolver)

    assert H3_REFERENCE_TO_VIDEO == "minimax/h3-developer/reference-to-video"
    assert payload["model"] == H3_REFERENCE_TO_VIDEO
    assert payload["ratio"] == "9:16"
    assert payload["duration"] == 5
    assert payload["resolution"] == "768P"
    assert payload["prompt_expansion"] is False
    assert payload["refers"] == [
        {"url": "https://static.atlascloud.ai/character_mira.png", "type": "image"},
        {"url": "https://static.atlascloud.ai/storyboard_1.png", "type": "image"},
    ]
    assert resolver.resolved == ["character_mira", "storyboard_1"]
    assert "images" not in payload
    assert "Mira" in payload["prompt"]
    assert "Reference image 1: Mira" in payload["prompt"]
    assert "audible speech" in payload["prompt"]


async def test_multi_shot_sequence_is_flattened_in_chronological_prompt(provider):
    spec = RenderSpec(
        scene_id="s1", duration=5, prompt="story",
        reference_images=[ReferenceImage(name="Storyboard", asset_id="storyboard_1")],
        multi_shot=True, shot_type="customize",
        multi_prompt=[
            StoryboardShot(prompt="Mira arrives. Mira says, 「Hello」", duration=3),
            StoryboardShot(prompt="Mira waves. Mira says, 「Goodbye」", duration=2),
        ],
    )

    payload = await provider.build_payload(spec, FakeResolver())

    assert "Create one continuous, chronological video" in payload["prompt"]
    assert "Beat 1: Mira arrives. Mira says, 「Hello」" in payload["prompt"]
    assert "Beat 2: Mira waves. Mira says, 「Goodbye」" in payload["prompt"]


async def test_reference_video_is_passed_as_a_video_material(provider):
    resolver = FakeResolver()
    spec = RenderSpec(
        scene_id="s1", duration=5, prompt="continue this movement",
        video_asset_id="reference_clip",
    )

    payload = await provider.build_payload(spec, resolver)

    assert payload["refers"] == [
        {"url": "https://static.atlascloud.ai/reference_clip.mp4", "type": "video"}
    ]


async def test_h3_text_to_video_remains_available_without_references(provider):
    spec = RenderSpec(
        scene_id="s1", duration=5, prompt="p", model=H3_TEXT_TO_VIDEO
    )

    payload = await provider.build_payload(spec, FakeResolver())

    assert payload["model"] == H3_TEXT_TO_VIDEO
    assert "refers" not in payload


async def test_h3_developer_text_to_video_accepts_480p(monkeypatch):
    settings = Settings(_env_file=None, ATLASCLOUD_API_KEY="k", ATLAS_VIDEO_RESOLUTION="480P")
    monkeypatch.setattr("app.providers.atlascloud_video.get_settings", lambda: settings)
    provider = AtlasCloudVideoProvider(client=object())
    spec = RenderSpec(
        scene_id="s1", duration=5, prompt="p", model=H3_TEXT_TO_VIDEO
    )

    payload = await provider.build_payload(spec, FakeResolver())

    assert payload["resolution"] == "480P"


async def test_legacy_h3_reference_route_keeps_its_768p_minimum(monkeypatch):
    settings = Settings(_env_file=None, ATLASCLOUD_API_KEY="k", ATLAS_VIDEO_RESOLUTION="480P")
    monkeypatch.setattr("app.providers.atlascloud_video.get_settings", lambda: settings)
    provider = AtlasCloudVideoProvider(client=object())
    spec = RenderSpec(
        scene_id="s1", duration=5, prompt="p",
        model="minimax/h3/reference-to-video",
        reference_images=[ReferenceImage(name="Storyboard", asset_id="board")],
    )

    with pytest.raises(ProviderError, match="minimax/h3/reference-to-video"):
        await provider.build_payload(spec, FakeResolver())


async def test_reference_to_video_requires_at_least_one_reference(provider):
    spec = RenderSpec(scene_id="s1", duration=5, prompt="p")

    with pytest.raises(ProviderError, match="requires at least one image or video reference"):
        await provider.build_payload(spec, FakeResolver())
