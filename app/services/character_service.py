"""Character persistence + bible generation."""

from __future__ import annotations

from sqlmodel import Session, select

from app.agents.character_memory import build_character_bible
from app.config import get_settings
from app.errors import NotFoundError
from app.models import Asset, Character
from app.models.base import new_id, utcnow
from app.providers.atlascloud_client import get_atlas_client
from app.providers.atlascloud_image import AtlasCloudImageProvider
from app.providers.polling import poll_until_terminal
from app.providers.url_resolver import AtlasCloudUploadResolver
from app.services import media, project_service, style_service
from app.services.asset_gen_service import REFERENCE_STYLE_PREFIX

DEFAULT_ANGLES = [
    "front view, neutral expression",
    "3/4 left profile",
    "right side profile",
    "full-body standing pose",
]


def create_character(session: Session, *, name: str, description: str = "") -> Character:
    char = Character(
        name=name,
        description=description,
        project_id=project_service.active_project_id(session),
    )
    session.add(char)
    session.commit()
    session.refresh(char)
    return char


def get_character(session: Session, character_id: str) -> Character:
    char = session.get(Character, character_id)
    if char is None:
        raise NotFoundError(f"character {character_id} not found")
    return char


def list_characters(session: Session) -> list[Character]:
    pid = project_service.active_project_id(session)
    return list(
        session.exec(select(Character).where(Character.project_id == pid)).all()
    )


async def generate_bible(session: Session, character_id: str, notes: str) -> Character:
    """Run the character-memory agent and persist the bible onto the character."""
    char = get_character(session, character_id)
    ref_ids = list(char.reference_asset_ids_json or [])
    ref_descriptions = []
    for aid in ref_ids:
        asset = session.get(Asset, aid)
        if asset and asset.description:
            ref_descriptions.append(asset.description)

    bible = await build_character_bible(
        character_id=char.id,
        name=char.name,
        notes=notes,
        reference_asset_descriptions=ref_descriptions,
        reference_asset_ids=ref_ids,
        style=style_service.style_context(style_service.get_style(session)),
    )
    char.appearance = bible.appearance
    char.personality = bible.personality
    char.visual_rules_json = bible.visual_rules
    char.voice_rules_json = bible.voice_rules
    char.reference_asset_ids_json = bible.reference_asset_ids or ref_ids
    char.updated_at = utcnow()
    session.add(char)
    session.commit()
    session.refresh(char)
    return char


def _angle_prompt(char: Character, angle: str) -> str:
    rules = "; ".join(char.visual_rules_json or [])
    parts = [
        f"Consistent character reference sheet of {char.name}.",
        f"Appearance: {char.appearance}." if char.appearance else "",
        f"Continuity rules: {rules}." if rules else "",
        f"Shot: {angle}.",
        "Clean studio background, even lighting, same identity across angles, "
        "no text, no watermark.",
    ]
    return " ".join(p for p in parts if p)


async def generate_reference_sheets(
    session: Session,
    character_id: str,
    *,
    angles: list[str] | None = None,
    image_provider: AtlasCloudImageProvider | None = None,
) -> list[Asset]:
    """Generate consistent multi-angle reference images via ERNIE and store them
    as character_reference assets that later feed Kling reference-to-video.

    The project style guide is enforced on every sheet: its text is appended to
    each prompt (apply_style), and when the guide pins reference assets the
    sheets are generated with the edit (reference) model so they match the look
    exactly. Only style-guide refs are used here — cast sheets can't be, since
    this is the path that creates them."""
    settings = get_settings()
    char = get_character(session, character_id)
    angles = angles or DEFAULT_ANGLES
    provider = image_provider or AtlasCloudImageProvider(get_atlas_client())

    style = style_service.get_style(session)
    style_ref_ids = list(style.reference_asset_ids_json or []) if style else []
    reference_urls: list[str] = []
    if style_ref_ids:
        resolver = AtlasCloudUploadResolver(session, get_atlas_client())
        reference_urls = await resolver.resolve(style_ref_ids)

    dest_dir = settings.characters_dir / char.id
    created: list[Asset] = []
    ref_ids = list(char.reference_asset_ids_json or [])

    for idx, angle in enumerate(angles):
        styled_prompt = style_service.apply_style(_angle_prompt(char, angle), style)
        if reference_urls:
            payload = await provider.build_reference_payload(
                prompt=REFERENCE_STYLE_PREFIX + styled_prompt,
                images=reference_urls,
            )
        else:
            payload = await provider.build_payload(prompt=styled_prompt)
        job_id = await provider.submit(payload)
        result = await poll_until_terminal(
            provider, job_id,
            interval_s=settings.poll_interval_s, timeout_s=settings.poll_timeout_s,
        )
        if not result.output_urls:
            continue
        asset_id = new_id("asset")
        dest = dest_dir / f"{asset_id}.png"
        await media.download(result.output_urls[0], dest)
        asset = Asset(
            id=asset_id,
            project_id=char.project_id,
            type="character_reference",
            name=f"{char.name} — {angle}",
            file_path=str(dest),
            description=styled_prompt,
            character_id=char.id,
            tags_json=["character_reference", char.name],
        )
        session.add(asset)
        created.append(asset)
        ref_ids.append(asset_id)

    char.reference_asset_ids_json = ref_ids
    char.updated_at = utcnow()
    session.add(char)
    session.commit()
    for a in created:
        session.refresh(a)
    return created
