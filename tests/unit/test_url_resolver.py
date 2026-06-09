"""Unit test: AtlasCloudUploadResolver uploads once and caches the URL."""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401  (register tables)
from app.models import Asset
from app.providers.url_resolver import ATLAS_URL_KEY, AtlasCloudUploadResolver


class CountingAtlas:
    def __init__(self):
        self.uploads = 0

    async def upload_media(self, file_path: str) -> str:
        self.uploads += 1
        return f"https://static.atlascloud.ai/uploaded/{self.uploads}.png"


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


async def test_resolver_caches_url(session):
    asset = Asset(id="asset_a", type="prop", file_path="/tmp/a.png")
    session.add(asset)
    session.commit()

    atlas = CountingAtlas()
    resolver = AtlasCloudUploadResolver(session, atlas)

    url1 = await resolver.resolve_one("asset_a")
    url2 = await resolver.resolve_one("asset_a")

    assert url1 == url2
    assert atlas.uploads == 1  # second call served from cache
    refreshed = session.get(Asset, "asset_a")
    assert refreshed.metadata_json[ATLAS_URL_KEY] == url1
