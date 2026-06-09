"""Raw async HTTP client for AtlasCloud.

The ONLY place that talks to api.atlascloud.ai. All AtlasCloud contract details
(endpoint paths, auth header, response shape) live here, so when the live API
shape is confirmed only this file changes. Mirrors the user's reference code:
generateImage / generateVideo return {data:{id}}; prediction/{id} returns
{data:{status, outputs, error}}; uploadMedia returns {url}.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.errors import ProviderError


class AtlasCloudClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = httpx.AsyncClient(
            base_url=self._settings.atlascloud_base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {self._settings.atlascloud_api_key}"},
            timeout=httpx.Timeout(60.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post_json(self, path: str, payload: dict) -> dict:
        try:
            resp = await self._client.post(
                path, json=payload, headers={"Content-Type": "application/json"}
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f"AtlasCloud {path} -> {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"AtlasCloud {path} failed: {exc}") from exc
        return resp.json()

    @staticmethod
    def _prediction_id(body: dict) -> str:
        data = body.get("data") or body
        pid = data.get("id") or data.get("prediction_id")
        if not pid:
            raise ProviderError(f"AtlasCloud response missing prediction id: {body}")
        return pid

    async def generate_image(self, payload: dict) -> str:
        body = await self._post_json("/model/generateImage", payload)
        return self._prediction_id(body)

    async def generate_video(self, payload: dict) -> str:
        body = await self._post_json("/model/generateVideo", payload)
        return self._prediction_id(body)

    async def get_prediction(self, prediction_id: str) -> dict:
        """Return the normalised {status, outputs, error} data block."""
        try:
            resp = await self._client.get(f"/model/prediction/{prediction_id}")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"AtlasCloud poll failed: {exc}") from exc
        body = resp.json()
        return body.get("data") or body

    async def upload_media(self, file_path: str) -> str:
        """Upload a local file, return a hosted static.atlascloud.ai URL."""
        path = Path(file_path)
        if not path.exists():
            raise ProviderError(f"cannot upload missing file: {file_path}")
        try:
            with path.open("rb") as fh:
                resp = await self._client.post(
                    "/model/uploadMedia", files={"file": (path.name, fh)}
                )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"AtlasCloud uploadMedia failed: {exc}") from exc
        body = resp.json()
        data = body.get("data") or {}
        # AtlasCloud returns the hosted URL as data.download_url.
        url = body.get("url") or data.get("url") or data.get("download_url")
        if not url:
            raise ProviderError(f"uploadMedia response missing url: {body}")
        return url


_singleton: AtlasCloudClient | None = None


def get_atlas_client() -> AtlasCloudClient:
    global _singleton
    if _singleton is None:
        _singleton = AtlasCloudClient()
    return _singleton


def extract_outputs(data: dict) -> list[str]:
    """Pull output URLs from a prediction data block, tolerant of shape."""
    outputs: Any = data.get("outputs") or data.get("output") or []
    if isinstance(outputs, str):
        return [outputs]
    if isinstance(outputs, list):
        result = []
        for o in outputs:
            if isinstance(o, str):
                result.append(o)
            elif isinstance(o, dict):
                url = o.get("url") or o.get("video") or o.get("image")
                if url:
                    result.append(url)
        return result
    return []
