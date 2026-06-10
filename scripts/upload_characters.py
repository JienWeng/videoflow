"""One-off deterministic import: character-to-upload/*.jpeg -> Character + Asset
rows via the app's own services, then a live AtlasCloud upload (uploadMedia) and
a temperature-0 MiniMax probe. No LLM agents run for the import itself.

Run: uv run python scripts/upload_characters.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import engine, init_db
from app.models import Asset, Character
from app.providers.atlascloud_client import get_atlas_client
from app.providers.url_resolver import AtlasCloudUploadResolver
from app.services import asset_service, character_service

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "character-to-upload"


def get_or_create_character(session: Session, name: str) -> Character:
    existing = session.exec(select(Character).where(Character.name == name)).first()
    if existing:
        return existing
    return character_service.create_character(session, name=name)


def import_image(session: Session, char: Character, image: Path) -> Asset:
    """Idempotent: reuse the asset if this file was already imported for the char."""
    existing = session.exec(
        select(Asset).where(Asset.character_id == char.id, Asset.name == image.stem)
    ).first()
    if existing:
        return existing
    with image.open("rb") as fh:
        return asset_service.save_upload(
            session,
            filename=image.name,
            fileobj=fh,
            asset_type="character_reference",
            character_id=char.id,
        )


class Probe(BaseModel):
    """Trivial schema for the deterministic MiniMax connectivity check."""

    ok: bool
    echo: str


async def probe_minimax(model: str | None = None) -> str:
    from app.llm.structured_client import StructuredLLMClient

    client = StructuredLLMClient()
    result = await client.generate(
        response_model=Probe,
        system_prompt="Return ok=true and echo the user's word exactly.",
        user_prompt="videoflow",
        provider="minimax",
        model=model,
        temperature=0.0,
    )
    return f"ok={result.ok} echo={result.echo!r}"


async def main() -> None:
    init_db()
    images = sorted(UPLOAD_DIR.glob("*.jpeg"))
    if not images:
        print(f"no .jpeg files in {UPLOAD_DIR}")
        return

    with Session(engine) as session:
        resolver = AtlasCloudUploadResolver(session, get_atlas_client())
        for image in images:
            char = get_or_create_character(session, image.stem)
            asset = import_image(session, char, image)
            print(f"[local] {image.name} -> character={char.id} asset={asset.id}")
            try:
                url = await resolver.resolve_one(asset.id)
                print(f"[atlas] {asset.id} -> {url}")
            except Exception as exc:
                print(f"[atlas] {asset.id} FAILED: {exc}")

    from app.config import get_settings

    settings = get_settings()
    for model in (settings.minimax_text_model, "MiniMax-M2"):
        try:
            print(f"[minimax] {model}: {await probe_minimax(model)}")
        except Exception as exc:
            print(f"[minimax] {model} FAILED: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
