"""@Name mention auto-linking.

When "@Name" appears in a scene summary or shot prompt (typed by the user or
written by an agent), resolve it against known characters and assets and create
the relationship automatically.

Matching semantics:
- Exact, case-sensitive match on the name following '@'.
- Longest names are checked first, so "@Red Cup Deluxe" wins over "@Red Cup".
- The name must be followed by a non-word char or end-of-string, so "@Grace"
  never matches inside "@Graceland". CJK characters ARE \\w, so this is also
  conservative for CJK: "@乐乐 走过" matches the name 乐乐, but "@乐乐是我"
  does NOT (是 is a word char) — an embedded CJK name is never spliced.
- Precedence: characters are checked before assets; an asset that shares a
  character's name is skipped for that mention (the character wins).
"""

from __future__ import annotations

import re

from sqlmodel import Session, select

from app.models import Asset, Character, Scene, Shot
from app.models.base import utcnow
from app.services import scene_service


def find_mentions(text: str, names: dict[str, str]) -> list[str]:
    """Return ids whose @Name appears in `text`. `names` maps name -> id.

    Longest names are checked first; matched spans are blanked out so a shorter
    name never re-matches inside a longer mention it is a prefix of.
    """
    if not text or not names:
        return []
    found: list[str] = []
    remaining = text
    for name in sorted(names, key=len, reverse=True):
        pattern = re.compile("@" + re.escape(name) + r"(?!\w)")
        if pattern.search(remaining):
            found.append(names[name])
            remaining = pattern.sub(" " * (len(name) + 1), remaining)
    return found


def _names_to_ids(rows) -> dict[str, str]:
    """name -> id; skip empty names; on duplicates, first wins by sorted id."""
    out: dict[str, str] = {}
    for row in sorted(rows, key=lambda r: r.id):
        if row.name and row.name not in out:
            out[row.name] = row.id
    return out


def auto_link_scene(session: Session, scene_id: str) -> dict:
    """Scan scene.summary and every shot.prompt for @mentions and link them.

    - character mention in summary or any shot prompt -> add_cast_member
    - asset mention in a shot prompt -> attach_shot_asset
    - asset mention in the summary only -> scene.asset_ids_json
    """
    scene = scene_service.get_scene(session, scene_id)
    shots = scene_service.list_shots(session, scene_id)

    char_names = _names_to_ids(session.exec(select(Character)).all())
    asset_names = _names_to_ids(session.exec(select(Asset)).all())
    # Character precedence: an asset sharing a character's name is skipped.
    asset_names = {n: i for n, i in asset_names.items() if n not in char_names}

    result: dict = {"cast_added": [], "shot_assets_added": {}, "scene_assets_added": []}

    texts = [scene.summary or ""] + [shot.prompt or "" for shot in shots]
    existing_cast = set(scene.character_ids_json or [])
    for char_id in {cid for text in texts for cid in find_mentions(text, char_names)}:
        if char_id not in existing_cast:
            scene_service.add_cast_member(session, scene_id, char_id)
            result["cast_added"].append(char_id)

    for shot in shots:
        added = []
        existing = set(shot.asset_ids_json or [])
        for asset_id in find_mentions(shot.prompt or "", asset_names):
            if asset_id not in existing:
                scene_service.attach_shot_asset(session, shot.id, asset_id)
                added.append(asset_id)
        if added:
            result["shot_assets_added"][shot.id] = added

    summary_assets = [
        aid
        for aid in find_mentions(scene.summary or "", asset_names)
        if aid not in (scene.asset_ids_json or [])
    ]
    if summary_assets:
        # Reassign (never mutate in place) — JSON column change detection.
        scene.asset_ids_json = [*(scene.asset_ids_json or []), *summary_assets]
        scene.updated_at = utcnow()
        session.add(scene)
        session.commit()
        session.refresh(scene)
        result["scene_assets_added"] = summary_assets

    return result
