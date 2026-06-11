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

Bare-name enforcement (tag_bare_names): agents sometimes forget the '@'. A
deterministic pass rewrites bare character/asset names in SHOT PROMPTS to
@Name so the output is always database-tagged. Scene summaries are narrative
prose — rewriting them to @Name reads badly, so summaries get name DETECTION
(for linking) but are never rewritten. Names inside 「」 dialogue spans are
speech, not visual references: they are neither rewritten nor linked (the
captions/voice pipeline extracts quoted lines verbatim).
"""

from __future__ import annotations

import re

from sqlmodel import Session, select

from app.models import Asset, Character, Scene, Shot
from app.models.base import utcnow
from app.services import scene_service
from app.services.dialogue import DIALOGUE_RE


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


def tag_bare_names(text: str, names: dict[str, str]) -> tuple[str, list[str]]:
    """Rewrite bare entity names to @Name OUTSIDE 「」 dialogue spans.

    `names` maps name -> id (characters + assets; on a name collision the
    caller resolves precedence before building the dict). Returns
    (rewritten_text, matched_ids).

    - Already @-tagged name -> no double-tag, but the id IS reported.
    - Word-boundary semantics identical to asset_gen_service.tag_prompt
      ((?<!\\w)name(?!\\w)): "Grace" never fires inside "Graceland", and a CJK
      name embedded in a longer CJK run is never spliced (CJK chars are \\w).
    - Only the FIRST bare occurrence per name is tagged; later bare
      occurrences are left alone.
    - Names shorter than 2 characters are skipped (a 1-char name over-fires).
    - Longest names first, with matched spans blanked, so "Red Cup" never
      splices into "Red Cup Deluxe".
    """
    if not text or not names:
        return text, []

    # Mask dialogue spans with NUL (a non-word char, so boundary semantics at
    # span edges match the real 「」 quotes): matching runs on the masked copy,
    # edits are applied to the original at the same offsets.
    work = list(text)
    for span in DIALOGUE_RE.finditer(text):
        work[span.start() : span.end()] = "\x00" * (span.end() - span.start())
    masked = "".join(work)

    matched: list[str] = []
    insert_at: list[int] = []  # offsets in `text` where an '@' is inserted
    for name in sorted(names, key=len, reverse=True):
        if len(name) < 2:
            continue
        at_pattern = re.compile("@" + re.escape(name) + r"(?!\w)")
        bare_pattern = re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)")
        blank = lambda m: "\x00" * (m.end() - m.start())  # noqa: E731
        if at_pattern.search(masked):
            matched.append(names[name])
        else:
            bare = bare_pattern.search(masked)
            if bare is None:
                continue
            matched.append(names[name])
            insert_at.append(bare.start())
        # Blank every occurrence (tagged AND bare) so a shorter name never
        # re-matches inside a longer name it is a prefix of.
        masked = at_pattern.sub(blank, masked)
        masked = bare_pattern.sub(blank, masked)

    if not insert_at:
        return text, matched
    out = text
    for pos in sorted(insert_at, reverse=True):
        out = out[:pos] + "@" + out[pos:]
    return out, matched


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

    Bare-name enforcement runs first: bare names in SHOT PROMPTS are rewritten
    to @Name (a mechanical normalization — written directly to the row with no
    Revision, like add_cast_member), then the @-based pass links as usual.
    The scene SUMMARY is never rewritten (narrative prose); bare names found
    there only contribute to linking.
    """
    scene = scene_service.get_scene(session, scene_id)
    shots = scene_service.list_shots(session, scene_id)

    char_names = _names_to_ids(session.exec(select(Character)).all())
    asset_names = _names_to_ids(session.exec(select(Asset)).all())
    # Character precedence: an asset sharing a character's name is skipped.
    asset_names = {n: i for n, i in asset_names.items() if n not in char_names}
    all_names = {**char_names, **asset_names}

    # Bare-name pass: rewrite shot prompts in place (outside 「」 dialogue).
    rewritten: list[Shot] = []
    for shot in shots:
        new_prompt, _ = tag_bare_names(shot.prompt or "", all_names)
        if new_prompt != (shot.prompt or ""):
            shot.prompt = new_prompt
            shot.updated_at = utcnow()
            session.add(shot)
            rewritten.append(shot)
    if rewritten:
        session.commit()
        for shot in rewritten:
            session.refresh(shot)

    # Summary: DETECT bare names (dialogue-masked) without rewriting.
    _, summary_bare_ids = tag_bare_names(scene.summary or "", all_names)
    char_ids = set(char_names.values())
    summary_bare_chars = {i for i in summary_bare_ids if i in char_ids}
    summary_bare_assets = [i for i in summary_bare_ids if i not in char_ids]

    result: dict = {"cast_added": [], "shot_assets_added": {}, "scene_assets_added": []}

    texts = [scene.summary or ""] + [shot.prompt or "" for shot in shots]
    existing_cast = set(scene.character_ids_json or [])
    mentioned_chars = {
        cid for text in texts for cid in find_mentions(text, char_names)
    } | summary_bare_chars
    for char_id in mentioned_chars:
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

    summary_mentions = find_mentions(scene.summary or "", asset_names)
    summary_mentions += [a for a in summary_bare_assets if a not in summary_mentions]
    summary_assets = [
        aid for aid in summary_mentions if aid not in (scene.asset_ids_json or [])
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
