"""Capability metadata + settings-resolver-read params for the AtlasCloud
image and video providers.

These lock in two things:

1. Provider hard-limits are declared as module-level metadata (duration clamp,
   reference-image caps) rather than scattered magic numbers.
2. The limits / image-gen params are read through the Foundation settings
   resolver, so they are tunable per-deployment WITHOUT changing the default
   behaviour (a fresh DB resolves to the exact same numbers as before).
"""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.config import Settings
from app.providers import atlascloud_image as image_mod
from app.providers import atlascloud_video as video_mod
from app.providers.atlascloud_image import AtlasCloudImageProvider
from app.providers.atlascloud_video import AtlasCloudVideoProvider
from app.providers.model_ids import H3_REFERENCE_TO_VIDEO
from app.schemas import ReferenceImage, RenderSpec
from app.services import settings_service


@pytest.fixture
def session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _settings(**kw) -> Settings:
    base = {"ATLASCLOUD_API_KEY": "k", "MINIMAX_API_KEY": "k"}
    base.update(kw)
    return Settings(_env_file=None, **base)


class _SessionResolver:
    """A resolver stand-in that also carries a `_session` (like the real
    AtlasCloudUploadResolver) so the video provider can read settings."""

    def __init__(self, session):
        self._session = session
        self.resolved: list[str] = []

    async def resolve(self, asset_ids):
        self.resolved.extend(asset_ids)
        return [f"https://static.atlascloud.ai/{a}.png" for a in asset_ids]

    async def resolve_one(self, asset_id):
        return f"https://static.atlascloud.ai/{asset_id}.mp4"


# --------------------------------------------------------------- video metadata

def test_video_declares_duration_clamp_metadata():
    assert video_mod.VIDEO_MIN_DURATION == 4
    assert video_mod.VIDEO_MAX_DURATION == 15
    assert video_mod.DEFAULT_VIDEO_MAX_REFS == 7
    assert _settings().atlas_video_model == H3_REFERENCE_TO_VIDEO
    caps = video_mod.CAPABILITIES
    assert caps["min_duration_s"] == 4
    assert caps["max_duration_s"] == 15
    assert caps["default_reference_image_limit"] == 7
    assert caps["required_reference_count"] == 1
    assert caps["resolutions"] == ["2K", "480P", "768P"]


@pytest.mark.parametrize(
    "requested,expected",
    [(1, 4), (2, 4), (3, 4), (9, 9), (15, 15), (20, 15)],
)
async def test_duration_is_clamped_to_metadata_range(
    monkeypatch, session, requested, expected
):
    monkeypatch.setattr(video_mod, "get_settings", _settings)
    provider = AtlasCloudVideoProvider(client=object())
    spec = RenderSpec(
        scene_id="s1",
        duration=15,  # construct valid, then mutate to exercise the clamp
        prompt="p",
        reference_images=[ReferenceImage(name="r", asset_id="a")],
    )
    spec.duration = requested
    payload = await provider.build_payload(spec, _SessionResolver(session))
    assert payload["duration"] == expected


async def test_video_max_refs_default_unchanged(monkeypatch, session):
    """With no app_settings row, the cap resolves to the config default (7)."""
    monkeypatch.setattr(video_mod, "get_settings", _settings)
    provider = AtlasCloudVideoProvider(client=object())
    spec = RenderSpec(
        scene_id="s1", duration=5, prompt="p",
        reference_images=[
            ReferenceImage(name=f"r{i}", asset_id=f"a{i}") for i in range(9)
        ],
    )
    payload = await provider.build_payload(spec, _SessionResolver(session))
    assert len(payload["refers"]) == 7


async def test_video_max_refs_tunable_via_resolver(monkeypatch, session):
    """A persisted max_video_refs app-setting overrides the default cap live."""
    monkeypatch.setattr(video_mod, "get_settings", _settings)
    settings_service.set_app_setting(session, "max_video_refs", 3)
    provider = AtlasCloudVideoProvider(client=object())
    spec = RenderSpec(
        scene_id="s1", duration=5, prompt="p",
        reference_images=[
            ReferenceImage(name=f"r{i}", asset_id=f"a{i}") for i in range(9)
        ],
    )
    payload = await provider.build_payload(spec, _SessionResolver(session))
    assert len(payload["refers"]) == 3


async def test_video_falls_back_to_config_without_session(monkeypatch):
    """A resolver without a `_session` (legacy/test fakes) still caps at config
    default — no crash, identical behaviour."""
    monkeypatch.setattr(video_mod, "get_settings", _settings)

    class _NoSessionResolver:
        async def resolve(self, asset_ids):
            return [f"https://x/{a}.png" for a in asset_ids]

        async def resolve_one(self, asset_id):
            return f"https://x/{asset_id}.mp4"

    provider = AtlasCloudVideoProvider(client=object())
    spec = RenderSpec(
        scene_id="s1", duration=5, prompt="p",
        reference_images=[
            ReferenceImage(name=f"r{i}", asset_id=f"a{i}") for i in range(9)
        ],
    )
    payload = await provider.build_payload(spec, _NoSessionResolver())
    assert len(payload["refers"]) == 7


# --------------------------------------------------------------- image metadata

def test_image_declares_storyboard_cap_and_size_default():
    assert image_mod.STORYBOARD_IMAGE_CAP == 10
    assert image_mod.DEFAULT_IMAGE_SIZE == "1024x1024"
    caps = image_mod.CAPABILITIES
    assert caps["max_reference_images"] == 10
    assert caps["default_size"] == "1024x1024"


async def test_image_payload_uses_current_atlascloud_contract_without_session(monkeypatch):
    monkeypatch.setattr(image_mod, "get_settings", _settings)
    provider = AtlasCloudImageProvider(client=object())
    payload = await provider.build_payload(prompt="cinematic night city", n=2)
    assert payload == {
        "model": "openai/gpt-image-2/text-to-image",
        "prompt": "cinematic night city",
        "size": "1024x1024",
        "quality": "low",
        "n": 2,
        "output_format": "jpeg",
        "enable_sync_mode": False,
        "enable_base64_output": False,
    }


async def test_image_params_tunable_via_resolver(monkeypatch, session):
    """Image-gen params resolve from the settings store when a session is wired."""
    monkeypatch.setattr(image_mod, "get_settings", _settings)
    settings_service.set_app_setting(session, "image_model", "baidu/custom")
    # Size and quality are supported payload fields. Insert their resolver rows
    # directly because they aren't exposed in the settings form.
    from app.models.setting import AppSetting

    for k, v in (
        ("image_size", "768x768"),
        ("image_quality", "medium"),
    ):
        session.add(AppSetting(key=k, scope="global", value=v))
    session.commit()

    provider = AtlasCloudImageProvider(client=object(), session=session)
    payload = await provider.build_payload(prompt="x")
    assert payload["model"] == "baidu/custom"
    assert payload["size"] == "768x768"
    assert payload["quality"] == "medium"
    assert "num_inference_steps" not in payload


async def test_reference_payload_caps_at_storyboard_metadata(monkeypatch):
    monkeypatch.setattr(image_mod, "get_settings", _settings)
    provider = AtlasCloudImageProvider(client=object())
    images = [f"https://x/{i}.png" for i in range(15)]
    payload = await provider.build_reference_payload(
        prompt="grid", images=images, aspect_ratio="9:16"
    )
    assert len(payload["images"]) == image_mod.STORYBOARD_IMAGE_CAP
    assert payload["images"] == images[:10]
