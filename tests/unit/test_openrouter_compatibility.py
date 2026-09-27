"""Regression coverage for the OpenRouter media API boundary."""

import asyncio
import base64

import httpx
import pytest
from sqlmodel import SQLModel, Session, create_engine

from app.models import Asset
from app.providers.openrouter_client import OpenRouterClient
from app.providers.openrouter_image import OpenRouterImageProvider
from app.providers.openrouter_video import OpenRouterVideoProvider
from app.providers.url_resolver import OpenRouterAssetResolver
from app.schemas.render_schema import RenderSpec


class VideoClient:
    async def get_video_models(self):
        return [{
            "id": "vendor/model", "supported_durations": [4, 8],
            "supported_resolutions": ["720p", "1080p"],
            "supported_aspect_ratios": ["9:16", "16:9"],
        }]


class Resolver:
    async def resolve(self, asset_ids):
        return [f"https://cdn.test/{asset_id}.png" for asset_id in asset_ids]


def test_openrouter_video_uses_guidance_references_and_frame_anchors_separately():
    spec = RenderSpec(
        provider="openrouter", model="vendor/model", scene_id="scene",
        duration=8, prompt="A person enters the room",
        extra_image_asset_ids=["guide"],
    )
    payload = asyncio.run(OpenRouterVideoProvider(client=VideoClient()).build_payload(spec, Resolver()))
    assert payload["input_references"] == [
        {"type": "image_url", "image_url": {"url": "https://cdn.test/guide.png"}}
    ]
    assert "frame_images" not in payload


def test_openrouter_video_uses_only_explicit_frame_anchors():
    spec = RenderSpec(
        provider="openrouter", model="vendor/model", scene_id="scene",
        duration=8, prompt="A person enters the room", first_frame_asset_id="start",
    )
    payload = asyncio.run(OpenRouterVideoProvider(client=VideoClient()).build_payload(spec, Resolver()))
    assert payload["frame_images"] == [{
        "type": "image_url", "image_url": {"url": "https://cdn.test/start.png"},
        "frame_type": "first_frame",
    }]
    assert "input_references" not in payload


def test_openrouter_video_rejects_duration_outside_model_catalog():
    spec = RenderSpec(
        provider="openrouter", model="vendor/model", scene_id="scene",
        duration=5, prompt="A person enters the room",
    )
    with pytest.raises(ValueError, match="supported durations: \\[4, 8\\]"):
        asyncio.run(OpenRouterVideoProvider(client=VideoClient()).build_payload(spec, Resolver()))


def test_openrouter_asset_resolver_embeds_local_asset_as_data_url(tmp_path):
    image = tmp_path / "reference.png"
    image.write_bytes(b"png-bytes")
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Asset(id="asset1", file_path=str(image)))
        session.commit()
        result = asyncio.run(OpenRouterAssetResolver(session).resolve(["asset1"]))
    assert result == ["data:image/png;base64," + base64.b64encode(b"png-bytes").decode()]


def test_openrouter_image_provider_preserves_all_outputs_and_media_type():
    provider = OpenRouterImageProvider(client=object())
    provider._results["job"] = {"data": [
        {"b64_json": "YWJj", "media_type": "image/webp"},
        {"b64_json": "ZGVm", "media_type": "image/jpeg"},
    ]}
    result = asyncio.run(provider.poll("job"))
    assert result.status == "succeeded"
    assert result.output_urls == ["data:image/webp;base64,YWJj", "data:image/jpeg;base64,ZGVm"]


def test_media_download_uses_actual_openrouter_image_file_extension(tmp_path):
    from app.services.media import download

    output = asyncio.run(download("data:image/webp;base64,YWJj", tmp_path / "asset.png"))
    assert output.name == "asset.webp"
    assert output.read_bytes() == b"abc"


def test_openrouter_client_downloads_video_with_bearer_auth():
    client = OpenRouterClient.__new__(OpenRouterClient)
    paths = []

    def handler(request):
        paths.append(str(request.url))
        return httpx.Response(200, content=b"video-bytes", headers={"content-type": "video/mp4"})

    client._client = httpx.AsyncClient(
        base_url="https://openrouter.test/api/v1",
        headers={"Authorization": "Bearer test-key"},
        transport=httpx.MockTransport(handler),
    )
    content, media_type = asyncio.run(client.download_video("job_123", 1))
    assert paths == ["https://openrouter.test/api/v1/videos/job_123/content?index=1"]
    assert content == b"video-bytes"
    assert media_type == "video/mp4"
    asyncio.run(client._client.aclose())


def test_openrouter_image_payload_accepts_selected_model():
    provider = OpenRouterImageProvider(client=object())
    payload = asyncio.run(provider.build_payload(prompt="A house", model="vendor/image", n=2))
    assert payload["model"] == "vendor/image"


def test_model_defaults_follow_openrouter_provider_setting():
    from sqlmodel import Session, SQLModel, create_engine
    from app.config import Settings
    from app.services import settings_service

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    settings = Settings(
        _env_file=None,
        DEFAULT_VIDEO_PROVIDER="openrouter",
        DEFAULT_IMAGE_PROVIDER="openrouter",
        OPENROUTER_VIDEO_MODEL="vendor/video",
        OPENROUTER_IMAGE_MODEL="vendor/image",
    )
    with Session(engine) as db:
        assert settings_service.resolve(db, "video_model", settings=settings) == "vendor/video"
        assert settings_service.resolve(db, "image_model", settings=settings) == "vendor/image"
        settings_service.set_app_setting(db, "default_video_provider", "atlascloud")
        assert settings_service.resolve(db, "video_model", settings=settings) == settings.atlas_video_model


def test_render_route_uses_configured_openrouter_route_when_omitted(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from sqlmodel import Session, SQLModel, create_engine
    from app.api import render as render_api
    from app.services import settings_service

    engine = create_engine(f"sqlite:///{tmp_path / 'settings.db'}")
    SQLModel.metadata.create_all(engine)
    captured = {}

    async def start_render(_session, spec):
        captured.update(provider=spec.provider, model=spec.model)
        return SimpleNamespace(id="job1", status="pending")

    monkeypatch.setattr(render_api.render_service, "start_render", start_render)
    with Session(engine) as db:
        settings_service.set_app_setting(db, "default_video_provider", "openrouter")
        settings_service.set_app_setting(db, "video_model", "vendor/video")
        request = RenderSpec(scene_id="s1", duration=8, prompt="A room")
        asyncio.run(render_api.render(request, db))

    assert captured == {"provider": "openrouter", "model": "vendor/video"}


def test_expired_is_terminal_failure():
    from app.providers.base import normalise_status
    assert normalise_status("expired") == "failed"
