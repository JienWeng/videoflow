"""Unit tests for AtlasCloudClient response handling (httpx MockTransport)."""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.errors import ProviderError
from app.providers.atlascloud_client import AtlasCloudClient


def make_client(handler) -> AtlasCloudClient:
    settings = Settings(ATLASCLOUD_API_KEY="k", MINIMAX_API_KEY="k")
    client = AtlasCloudClient(settings)
    client._client = httpx.AsyncClient(
        base_url="https://api.atlascloud.ai/api/v1",
        transport=httpx.MockTransport(handler),
    )
    return client


async def test_get_prediction_returns_failed_data_despite_http_500():
    """AtlasCloud wraps terminally-failed jobs in HTTP 500; the data block is
    still authoritative and must reach the poll loop as status=failed."""

    def handler(request):
        return httpx.Response(500, json={
            "code": 500,
            "message": "failed to parse upstream response",
            "data": {"id": "p1", "status": "failed",
                     "error": "failed to parse upstream response"},
        })

    data = await make_client(handler).get_prediction("p1")
    assert data["status"] == "failed"
    assert "upstream" in data["error"]


async def test_get_prediction_http_error_without_data_raises():
    def handler(request):
        return httpx.Response(502, text="<html>bad gateway</html>")

    with pytest.raises(ProviderError):
        await make_client(handler).get_prediction("p1")


async def test_generate_image_returns_full_data_block():
    """Sync-mode image generation returns outputs in the submit response."""

    def handler(request):
        return httpx.Response(200, json={
            "code": 200,
            "data": {"id": "p2", "status": "completed",
                     "outputs": ["https://x/img.png"]},
        })

    data = await make_client(handler).generate_image({"prompt": "x"})
    assert data["id"] == "p2"
    assert data["outputs"] == ["https://x/img.png"]
