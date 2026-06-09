"""Asset id -> public URL resolution.

AtlasCloud needs publicly-reachable URLs for reference images/videos, but assets
live in local /storage. The resolver uploads a local asset to AtlasCloud once and
caches the returned URL on the asset's metadata_json (key 'atlas_url') so repeat
renders never re-upload. Swappable for Base64/Bucket strategies via the protocol.
"""

from __future__ import annotations

from typing import Protocol

from sqlmodel import Session

from app.errors import NotFoundError, ProviderError
from app.models import Asset
from app.models.base import utcnow

ATLAS_URL_KEY = "atlas_url"


class AssetUrlResolver(Protocol):
    async def resolve(self, asset_ids: list[str]) -> list[str]: ...
    async def resolve_one(self, asset_id: str) -> str: ...


class AtlasCloudUploadResolver:
    def __init__(self, session: Session, atlas_client) -> None:
        self._session = session
        self._atlas = atlas_client

    async def resolve_one(self, asset_id: str) -> str:
        asset = self._session.get(Asset, asset_id)
        if asset is None:
            raise NotFoundError(f"asset {asset_id} not found")
        meta = dict(asset.metadata_json or {})
        cached = meta.get(ATLAS_URL_KEY)
        if cached:
            return cached
        if not asset.file_path:
            raise ProviderError(f"asset {asset_id} has no file to upload")
        url = await self._atlas.upload_media(asset.file_path)
        meta[ATLAS_URL_KEY] = url
        meta["atlas_url_uploaded_at"] = utcnow().isoformat()
        asset.metadata_json = meta
        self._session.add(asset)
        self._session.commit()
        return url

    async def resolve(self, asset_ids: list[str]) -> list[str]:
        urls = []
        for aid in asset_ids:
            urls.append(await self.resolve_one(aid))
        return urls
