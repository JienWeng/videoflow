"""Project StyleGuide service — singleton get/upsert plus AI ingest."""

from __future__ import annotations

from sqlmodel import Session, select

from app.agents.style_agent import derive_style
from app.models import Asset, Character, Scene, StyleGuide
from app.models.base import utcnow

# Fields the ingest agent owns (overwritten on every ingest).
DERIVED_FIELDS = ("style_prompt", "palette", "lighting", "audience", "tone")

_INGEST_ASSET_LIMIT = 10


def style_suffix(style: StyleGuide | None) -> str:
    """Combined style text appended to image prompts; '' when no guide."""
    if style is None:
        return ""
    parts = [
        style.style_prompt,
        f"palette: {style.palette}" if style.palette else "",
        f"lighting: {style.lighting}" if style.lighting else "",
    ]
    joined = "; ".join(p for p in parts if p)
    return f". Style: {joined}" if joined else ""


def apply_style(prompt: str, style: StyleGuide | None) -> str:
    """Deterministically enforce the style guide on an image prompt.

    Idempotent (the suffix is appended at most once) and a no-op when there is
    no guide or the guide has no visual fields."""
    suffix = style_suffix(style)
    if not suffix or suffix in prompt:
        return prompt
    return prompt.rstrip().rstrip(".") + suffix


def style_context(style: StyleGuide | None) -> dict | None:
    """Non-empty descriptive fields as a dict for agent context blocks
    (rendered as a "Project style guide" block); None when nothing to say."""
    if style is None:
        return None
    ctx = {k: v for k in DERIVED_FIELDS if (v := getattr(style, k))}
    return ctx or None


def get_style(session: Session) -> StyleGuide | None:
    """Return the singleton StyleGuide row (latest by created_at if several)."""
    rows = session.exec(
        select(StyleGuide).order_by(StyleGuide.created_at.desc())  # type: ignore[attr-defined]
    ).all()
    return rows[0] if rows else None


def upsert_style(
    session: Session,
    *,
    name: str | None = None,
    style_prompt: str | None = None,
    palette: str | None = None,
    lighting: str | None = None,
    audience: str | None = None,
    tone: str | None = None,
    reference_asset_ids: list[str] | None = None,
) -> StyleGuide:
    """Update the singleton row (create it if missing). Partial: only non-None
    fields are applied. reference_asset_ids are validated — unknown ids dropped."""
    style = get_style(session) or StyleGuide()
    if name is not None:
        style.name = name
    if style_prompt is not None:
        style.style_prompt = style_prompt
    if palette is not None:
        style.palette = palette
    if lighting is not None:
        style.lighting = lighting
    if audience is not None:
        style.audience = audience
    if tone is not None:
        style.tone = tone
    if reference_asset_ids is not None:
        style.reference_asset_ids_json = [
            aid for aid in reference_asset_ids if session.get(Asset, aid) is not None
        ]
    style.updated_at = utcnow()
    session.add(style)
    session.commit()
    session.refresh(style)
    return style


async def ingest_style(session: Session) -> StyleGuide:
    """Derive the project style from scenes/characters/assets and upsert the
    five derived fields (name + reference assets are kept)."""
    scenes = [
        {"title": s.title, "summary": s.summary, "aspect_ratio": s.aspect_ratio}
        for s in session.exec(select(Scene)).all()
    ]
    characters = [
        {"name": c.name, "appearance": c.appearance}
        for c in session.exec(select(Character)).all()
    ]
    assets = [
        {"name": a.name, "description": a.description}
        for a in session.exec(select(Asset).limit(_INGEST_ASSET_LIMIT)).all()
    ]
    spec = await derive_style(scenes=scenes, characters=characters, assets=assets)
    return upsert_style(session, **{f: getattr(spec, f) for f in DERIVED_FIELDS})
