"""OpenRouter media API client for dedicated image/video endpoints."""

from __future__ import annotations

import httpx
from urllib.parse import quote

from app.config import Settings, get_settings
from app.errors import ProviderError


class OpenRouterClient:
    def __init__(self, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        api_key = settings.openrouter_api_key
        base_url = settings.openrouter_base_url
        try:
            from sqlmodel import Session
            from app.database import engine
            from app.services import settings_service

            with Session(engine) as session:
                api_key = settings_service.effective_key(session, "openrouter", settings) or api_key
                base_url = settings_service.effective_base_url(session, "openrouter", settings) or base_url
        except Exception:
            pass
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(60.0),
        )

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = await self._client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"OpenRouter {path} failed: HTTP {exc.response.status_code} {exc.response.text[:300]}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"OpenRouter {path} failed: {exc}") from exc

    async def create_video(self, payload: dict) -> dict:
        return await self._request("POST", "/videos", json=payload)

    async def get_video(self, job_id: str) -> dict:
        return await self._request("GET", f"/videos/{job_id}")

    async def get_video_models(self) -> list[dict]:
        response = await self._request("GET", "/videos/models")
        data = response.get("data", [])
        return [item for item in data if isinstance(item, dict)]

    async def download_video(self, job_id: str, index: int = 0) -> tuple[bytes, str]:
        """Download a completed video through the authenticated content endpoint."""
        try:
            response = await self._client.get(
                f"/videos/{quote(job_id, safe='')}/content", params={"index": index}
            )
            response.raise_for_status()
            return response.content, response.headers.get("content-type", "video/mp4")
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f"OpenRouter video download failed: HTTP {exc.response.status_code} {exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"OpenRouter video download failed: {exc}") from exc

    async def create_image(self, payload: dict) -> dict:
        return await self._request("POST", "/images", json=payload)

    async def create_embeddings(self, payload: dict) -> dict:
        return await self._request("POST", "/embeddings", json=payload)

    async def rerank(self, payload: dict) -> dict:
        return await self._request("POST", "/rerank", json=payload)
