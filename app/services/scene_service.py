"""Script / scene / shot generation + persistence."""

from __future__ import annotations

import logging

from sqlmodel import Session, select

from app.agents import refine_agent
from app.agents.idea_agent import develop_idea
from app.config import get_settings
from app.agents.scene_agent import generate_scene
from app.agents.script_agent import generate_script
from app.agents.shot_agent import generate_shots
from app.errors import NotFoundError, ValidationFailedError
from app.models import Asset, Character, Revision, Scene, Script, Shot
from app.models.base import new_id, utcnow
from app.schemas import CharacterBible, IdeaOptions, SceneSpec, ScriptDraft, ShotSpec
from app.services import project_service, style_service
from app.services.dialogue import has_dialogue

logger = logging.getLogger(__name__)

DIALOGUE_FIX_INSTRUCTION = (
    "Ensure this shot has exactly ONE spoken line in 「」 quotes, PACED to fill "
    "its duration at a brisk 170-200 WPM (≈3 English words or ~5 Chinese "
    "characters per second) — add one, or resize an existing line so it fills "
    "the shot without dead air or rushing; change nothing else."
)


def _norm_name(name: str) -> str:
    """Case-insensitive, whitespace-normalized form ("Red  Cup" == "red cup").
    Local copy of asset_gen_service._norm_name — importing it at module level
    would create a circular import (asset_gen_service imports scene_service)."""
    return " ".join(name.split()).casefold()


# Name-like prefixes the agents tend to invent ("asset_教室", "char_乐乐",
# "character_Grace"). Longest first so "character_" wins over "char_".
_ENTITY_ID_PREFIXES = ("character_", "char_", "asset_")


def resolve_entity_ids(session: Session, ids: list[str], *, kind: str) -> list[str]:
    """Map LLM-supplied ids onto REAL rows. kind: 'asset' | 'character'.

    Deterministic enforcement for hallucinated ids: the scene/shot agents are
    told to use real ids from the context, but sometimes invent name-like ids
    ("asset_教室") instead. Resolution:
    - ids that exist in the DB pass through;
    - unknown ids are treated as names: strip a leading 'asset_'/'char_'/
      'character_' prefix, then match (whitespace-normalized, casefolded)
      against Asset.name / Character.name — the matching row's REAL id is used;
    - irrecoverable ids are dropped with a warning.
    Order preserved, deduplicated."""
    model = Asset if kind == "asset" else Character
    by_name: dict[str, str] | None = None  # lazy: only built on a miss
    seen: set[str] = set()
    out: list[str] = []
    for raw in ids or []:
        rid = raw
        if session.get(model, rid) is None:
            if by_name is None:
                pid = project_service.active_project_id(session)
                by_name = {
                    _norm_name(row.name): row.id
                    for row in session.exec(
                        select(model).where(model.project_id == pid)
                    )
                    if row.name
                }
            candidate = rid
            for prefix in _ENTITY_ID_PREFIXES:
                if candidate.casefold().startswith(prefix):
                    candidate = candidate[len(prefix):]
                    break
            real = by_name.get(_norm_name(candidate))
            if real is None:
                logger.warning(
                    "dropping unknown %s id %r (no row and no name match)", kind, raw
                )
                continue
            logger.info("resolved hallucinated %s id %r -> %s", kind, raw, real)
            rid = real
        if rid not in seen:
            seen.add(rid)
            out.append(rid)
    return out


def _character_catalog(
    session: Session, exclude_ids: set[str] | None = None
) -> list[dict]:
    """Compact {name, appearance} catalog of every character (minus
    exclude_ids) for agent context blocks. The agents are instructed to cast
    these by their EXACT names so auto_link_scene can @-tag and DB-link them."""
    pid = project_service.active_project_id(session)
    return [
        {"name": c.name, "appearance": (c.appearance or "")[:160]}
        for c in session.exec(
            select(Character).where(Character.project_id == pid)
        )
        if c.id not in (exclude_ids or set())
    ]


def character_to_bible(char: Character) -> CharacterBible:
    return CharacterBible(
        character_id=char.id,
        name=char.name,
        appearance=char.appearance,
        personality=char.personality,
        visual_rules=list(char.visual_rules_json or []),
        voice_rules=list(char.voice_rules_json or []),
        reference_asset_ids=list(char.reference_asset_ids_json or []),
    )


async def develop_script_idea(session: Session, *, idea: str) -> IdeaOptions:
    """Develop a raw idea into exactly two mature concept options (plus the
    agent's recommendation) using the same character + style context the
    script agent will later see.

    Deterministic enforcement: more than two options are truncated to two;
    zero options is a validation failure; recommended_index is clamped into
    range (a one-option result keeps index 0).
    """
    result = await develop_idea(
        idea=idea,
        characters=_character_catalog(session) or None,
        style=style_service.style_context(style_service.get_style(session)),
    )
    if not result.options:
        raise ValidationFailedError("idea agent returned no concept options")
    if len(result.options) > 2:
        result = result.model_copy(update={"options": result.options[:2]})
    if result.recommended_index >= len(result.options):
        result = result.model_copy(update={"recommended_index": 0})
    return result


async def create_script(
    session: Session,
    *,
    idea: str,
    target_duration: int | None = None,
    scene_count: int | None = None,
) -> tuple[Script, ScriptDraft]:
    """Generate a script, persist it as a Script row, and persist each scene
    stub as a Scene row linked back via script_id.

    When scene_count is set, the draft is truncated to at most that many
    scenes BEFORE persisting — this is the deterministic enforcement cap.
    """
    draft = await generate_script(
        idea=idea,
        target_duration=target_duration,
        scene_count=scene_count,
        style=style_service.style_context(style_service.get_style(session)),
        # Full character catalog so the agent casts existing characters by
        # their EXACT names (auto_link_scene later tags + links the mentions)
        # instead of inventing near-duplicates.
        characters=_character_catalog(session) or None,
    )
    if scene_count is not None and len(draft.scenes) > scene_count:
        draft = draft.model_copy(update={"scenes": draft.scenes[:scene_count]})
    pid = project_service.active_project_id(session)
    script = Script(
        idea=idea,
        project_id=pid,
        title=draft.title,
        summary=draft.summary,
        draft_json=draft.model_dump(),
    )
    session.add(script)
    for s in draft.scenes:
        scene = Scene(
            id=new_id("scene"),
            project_id=pid,
            script_id=script.id,
            title=s.title,
            summary=s.summary,
            duration=s.suggested_duration,
        )
        # Preserve the agent's scene_id mapping for traceability.
        scene.scene_json = {"script_scene_id": s.scene_id}
        session.add(scene)
    session.commit()
    session.refresh(script)
    return script, draft


def list_scripts(session: Session) -> list[Script]:
    pid = project_service.active_project_id(session)
    return list(session.exec(select(Script).where(Script.project_id == pid)).all())


def story_context(session: Session, scene: Scene) -> dict | None:
    """Overall story + sibling scenes for cross-scene continuity; None when
    the scene is alone with no script."""
    parts: dict = {}
    if scene.script_id and (script := session.get(Script, scene.script_id)):
        parts["story"] = {
            "idea": script.idea,
            "title": script.title,
            "summary": script.summary,
        }
        siblings = [
            s for s in list_scenes(session)
            if s.script_id == scene.script_id and s.id != scene.id
        ]
    else:
        siblings = [s for s in list_scenes(session) if s.id != scene.id]
    if siblings:
        parts["other_scenes"] = [
            {"title": s.title, "summary": (s.summary or "")[:200]} for s in siblings[:12]
        ]
    return parts or None


def create_scene(
    session: Session,
    *,
    title: str,
    summary: str = "",
    duration: int = 5,
    aspect_ratio: str = "16:9",
) -> Scene:
    """Plain scene create (no script) stamped with the active project."""
    scene = Scene(
        project_id=project_service.active_project_id(session),
        title=title,
        summary=summary,
        duration=duration,
        aspect_ratio=aspect_ratio,
    )
    session.add(scene)
    session.commit()
    session.refresh(scene)
    return scene


def get_scene(session: Session, scene_id: str) -> Scene:
    scene = session.get(Scene, scene_id)
    if scene is None:
        raise NotFoundError(f"scene {scene_id} not found")
    return scene


def list_scenes(session: Session) -> list[Scene]:
    pid = project_service.active_project_id(session)
    return list(session.exec(select(Scene).where(Scene.project_id == pid)).all())


async def expand_scene(session: Session, scene_id: str, character_ids: list[str] | None = None) -> Scene:
    """Run the scene agent and persist the full SceneSpec onto the scene row."""
    scene = get_scene(session, scene_id)
    bibles = []
    for cid in character_ids or scene.character_ids_json or []:
        char = session.get(Character, cid)
        if char:
            bibles.append(character_to_bible(char))

    # Database catalogs: every character NOT already in the bibles, and the
    # global asset library minus the scene's linked assets.  The agent casts /
    # references these by their EXACT names; auto_link_scene (hooked below)
    # converts the mentions into @tags and DB links.
    from app.services import asset_gen_service  # local import: avoids circularity

    cast_ids = {b.character_id for b in bibles}
    available_characters = _character_catalog(session, exclude_ids=cast_ids)
    library = [
        {"name": a.name, "type": a.type, "description": a.description}
        for a in asset_gen_service.gather_library(
            session, exclude_ids=set(scene.asset_ids_json or [])
        )
    ]

    spec = await generate_scene(
        scene_id=scene.id,
        title=scene.title,
        summary=scene.summary,
        suggested_duration=scene.duration,
        character_bibles=bibles,
        assets=_asset_dicts(session, scene.asset_ids_json or []),
        available_characters=available_characters or None,
        library=library or None,
        style=style_service.style_context(style_service.get_style(session)),
        story=story_context(session, scene),
    )
    # Deterministic enforcement: the agent's id lists may contain hallucinated
    # name-like ids — resolve them onto real rows (or drop them) BEFORE they
    # are persisted anywhere (columns AND scene_json).
    spec = spec.model_copy(
        update={
            "character_ids": resolve_entity_ids(
                session, spec.character_ids, kind="character"
            ),
            "asset_ids": resolve_entity_ids(session, spec.asset_ids, kind="asset"),
        }
    )
    scene.title = spec.title
    scene.summary = spec.summary
    scene.duration = spec.duration
    scene.aspect_ratio = spec.aspect_ratio
    scene.character_ids_json = spec.character_ids
    scene.asset_ids_json = spec.asset_ids
    scene.scene_json = spec.model_dump()
    scene.updated_at = utcnow()
    session.add(scene)
    session.commit()
    session.refresh(scene)
    _auto_link(session, scene.id)
    session.refresh(scene)
    return scene


def _auto_link(session: Session, scene_id: str) -> None:
    """Resolve @Name mentions in the summary/shot prompts into relationships."""
    from app.services import linking_service  # local import: avoids circularity

    linking_service.auto_link_scene(session, scene_id)


def _scene_to_spec(scene: Scene, session: Session) -> SceneSpec:
    """Build a SceneSpec for *scene*.

    Shot rows are the single source of truth: when Shot rows exist for this
    scene they are used (ordered by shot_order) and any shots embedded in
    scene_json are ignored.  The scene_json["shots"] fallback is only used in
    the post-expand, pre-create_shots window when no rows exist yet.
    """
    shot_rows = list_shots(session, scene.id)

    if shot_rows:
        shots = [
            ShotSpec(
                shot_id=row.id,
                duration=row.duration,
                prompt=row.prompt,
                camera=row.camera,
                movement=row.movement,
                asset_ids=list(row.asset_ids_json or []),
            )
            for row in shot_rows
        ]
        # Build the spec from scene fields + live shot rows; merge in any extra
        # top-level fields that may live in scene_json (e.g. character/asset lists
        # set by expand_scene) but always override the "shots" key.
        base: dict = {}
        if scene.scene_json:
            base = {k: v for k, v in scene.scene_json.items() if k != "shots"}
        base.update(
            scene_id=scene.id,
            title=scene.title,
            summary=scene.summary,
            duration=scene.duration,
            aspect_ratio=scene.aspect_ratio,
            character_ids=list(scene.character_ids_json or []),
            asset_ids=list(scene.asset_ids_json or []),
        )
        return SceneSpec.model_validate({**base, "shots": [s.model_dump() for s in shots]})

    # No shot rows yet: fall back to scene_json shots if present.
    if scene.scene_json and "shots" in scene.scene_json:
        return SceneSpec.model_validate(scene.scene_json)

    return SceneSpec(
        scene_id=scene.id,
        title=scene.title,
        summary=scene.summary,
        duration=scene.duration,
        aspect_ratio=scene.aspect_ratio,
        character_ids=list(scene.character_ids_json or []),
        asset_ids=list(scene.asset_ids_json or []),
        shots=[],
    )


def _asset_dicts(session: Session, asset_ids: list[str]) -> list[dict]:
    """Resolve asset ids to {name, type, description} dicts (deduplicated,
    missing ids skipped) for agent context blocks."""
    seen: set[str] = set()
    out: list[dict] = []
    for aid in asset_ids:
        if aid in seen:
            continue
        seen.add(aid)
        asset = session.get(Asset, aid)
        if asset:
            out.append(
                {"name": asset.name, "type": asset.type, "description": asset.description}
            )
    return out


async def create_shots(
    session: Session, scene_id: str, auto_assets: bool = True
) -> list[Shot]:
    """Run the shot agent and persist Shot rows for the scene.

    With auto_assets (default), missing props are then planned and generated
    automatically; asset-generation failures are logged and never fail the
    shots request."""
    scene = get_scene(session, scene_id)
    spec = _scene_to_spec(scene, session)

    bibles = []
    for cid in scene.character_ids_json or []:
        char = session.get(Character, cid)
        if char:
            bibles.append(character_to_bible(char))
    asset_ids = list(scene.asset_ids_json or [])
    for existing in list_shots(session, scene_id):
        asset_ids.extend(existing.asset_ids_json or [])

    shot_list = await generate_shots(
        scene=spec,
        characters=bibles or None,
        assets=_asset_dicts(session, asset_ids) or None,
        style=style_service.style_context(style_service.get_style(session)),
        story=story_context(session, scene),
    )

    # Replace: delete all existing shots for this scene BEFORE persisting the
    # new ones.  Asset context was already gathered above (before this point),
    # so the agent received the full historical context even though the rows are
    # now removed.  Render-history FK references are non-enforced and the /graph
    # endpoint already filters dangling edges, so deletion is safe.
    for old_shot in list_shots(session, scene_id):
        session.delete(old_shot)

    rows: list[Shot] = []
    for order, shot in enumerate(shot_list.shots):
        row = Shot(
            scene_id=scene.id,
            shot_order=order,
            duration=shot.duration,
            prompt=shot.prompt,
            camera=shot.camera,
            movement=shot.movement,
            # Hallucinated ids resolved to real rows / dropped before persisting.
            asset_ids_json=resolve_entity_ids(session, shot.asset_ids, kind="asset"),
            shot_json=shot.model_dump(),
        )
        session.add(row)
        rows.append(row)
    session.commit()
    await _ensure_shot_dialogue(session, scene, rows)
    await _enforce_dialogue_pace(session, scene, rows)
    _auto_link(session, scene.id)

    if auto_assets:
        from app.services import asset_gen_service  # local import: avoids circularity

        try:
            await asset_gen_service.generate_scene_assets(
                session, scene_id, instruction="", max_assets=4
            )
        except Exception:
            # Shots are still valuable when the image provider is down —
            # log and return them; props can be generated manually later.
            logger.exception("auto asset generation failed for scene %s", scene_id)
            session.rollback()  # discard any half-finished asset writes

    for row in rows:
        session.refresh(row)
    return rows


async def _ensure_shot_dialogue(session: Session, scene: Scene, rows: list[Shot]) -> None:
    """Bounded auto-fix: ONE refine pass per shot missing a 「」 spoken line.

    The refined prompt is applied only when it actually contains dialogue;
    agent failures or still-silent results keep the original prompt (no retry).
    """
    changed = False
    for row in rows:
        if has_dialogue(row.prompt):
            continue
        try:
            refinement = await refine_agent.refine_shot(
                shot={
                    "prompt": row.prompt,
                    "duration": row.duration,
                    "camera": row.camera,
                    "movement": row.movement,
                },
                scene_summary=scene.summary,
                instruction=DIALOGUE_FIX_INSTRUCTION,
            )
        except Exception:
            logger.exception(
                "dialogue auto-fix failed for shot %s; keeping original prompt", row.id
            )
            continue
        new_prompt = refinement.prompt
        if new_prompt and has_dialogue(new_prompt):
            row.prompt = new_prompt
            row.updated_at = utcnow()
            session.add(row)
            changed = True
        else:
            logger.warning(
                "dialogue auto-fix for shot %s returned no 「」 line; keeping original",
                row.id,
            )
    if changed:
        session.commit()


def _pace_distance(check: dict) -> int:
    """How far a line's unit-count is outside its pace band (0 when inside)."""
    return max(0, check["lo"] - check["count"], check["count"] - check["hi"])


async def _enforce_dialogue_pace(session: Session, scene: Scene, rows: list[Shot]) -> None:
    """Bounded auto-fix: ONE refine pass per shot whose 「」 line is mis-paced for
    its duration (too short -> slow/dead air, too long -> rushed). The rewritten
    line is applied only when it actually improves the pace (in-band or closer);
    agent failures keep the original. Pace targets resolve from settings
    (dialogue_wpm_*, dialogue_cps_zh_*)."""
    from app.services import dialogue, settings_service

    base = get_settings()
    # Honour project/global overrides of the pace targets, falling back to config.
    pid = project_service.active_project_id(session)
    settings = base.model_copy(update={
        k: settings_service.resolve(session, k, default=getattr(base, k), project_id=pid)
        for k in ("dialogue_wpm_min", "dialogue_wpm_max",
                  "dialogue_cps_zh_min", "dialogue_cps_zh_max")
    })
    changed = False
    for row in rows:
        check = dialogue.pace_check(row.prompt, row.duration, settings)
        if check["verdict"] in ("ok", "none"):
            continue
        units = "Chinese characters" if check["kind"] == "zh" else "English words"
        problem = (
            "too short (leaves dead air)"
            if check["verdict"] == "too_short"
            else "too long to say in time"
        )
        instruction = (
            f"The spoken 「」 line is {problem} for this {row.duration}s shot: it "
            f"has {check['count']} {units} but should be about {check['lo']}-"
            f"{check['hi']} {units} to fill the shot at a brisk 170-200 WPM pace. "
            "Rewrite ONLY the 「」 line to that length — keep it natural and "
            "on-topic; change nothing else."
        )
        try:
            refinement = await refine_agent.refine_shot(
                shot={
                    "prompt": row.prompt,
                    "duration": row.duration,
                    "camera": row.camera,
                    "movement": row.movement,
                },
                scene_summary=scene.summary,
                instruction=instruction,
            )
        except Exception:
            logger.exception(
                "dialogue pace-fix failed for shot %s; keeping original prompt", row.id
            )
            continue
        new_prompt = refinement.prompt
        if not new_prompt or not has_dialogue(new_prompt):
            continue
        new_check = dialogue.pace_check(new_prompt, row.duration, settings)
        if new_check["verdict"] == "ok" or _pace_distance(new_check) < _pace_distance(check):
            row.prompt = new_prompt
            row.updated_at = utcnow()
            session.add(row)
            changed = True
    if changed:
        session.commit()


def add_shot(
    session: Session,
    scene_id: str,
    *,
    prompt: str = "",
    duration: int | None = None,
    camera: str | None = None,
    movement: str | None = None,
    shot_order: int | None = None,
) -> Shot:
    """Append (or insert) a blank/manual shot on the scene.

    Without shot_order the shot lands at the end (max existing order + 1).
    With shot_order the new shot takes that slot and every existing shot at or
    after it is shifted down by one, keeping orders contiguous and stable."""
    scene = get_scene(session, scene_id)
    existing = list_shots(session, scene_id)
    if shot_order is None:
        order = (max((s.shot_order for s in existing), default=-1)) + 1
    else:
        order = max(0, shot_order)
        # Make room: bump every shot at/after the insertion point.
        for s in existing:
            if s.shot_order >= order:
                s.shot_order += 1
                s.updated_at = utcnow()
                session.add(s)
    row = Shot(
        scene_id=scene.id,
        shot_order=order,
        duration=duration if duration is not None else scene.duration,
        prompt=prompt,
        camera=camera,
        movement=movement,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def reorder_shots(session: Session, scene_id: str, ordered_ids: list[str]) -> list[Shot]:
    """Set each shot's shot_order from its position in *ordered_ids*.

    Only shots belonging to *scene_id* are touched; ids not in the scene are
    ignored, and any scene shot omitted from the list keeps its relative order
    after the supplied ones. Returns the scene's shots in the new order."""
    get_scene(session, scene_id)
    rows = list_shots(session, scene_id)
    by_id = {r.id: r for r in rows}
    seen: set[str] = set()
    order = 0
    for sid in ordered_ids:
        row = by_id.get(sid)
        if row is None or sid in seen:
            continue
        seen.add(sid)
        if row.shot_order != order:
            row.shot_order = order
            row.updated_at = utcnow()
            session.add(row)
        order += 1
    # Append any shots not named in ordered_ids, preserving their prior order.
    for row in rows:
        if row.id in seen:
            continue
        if row.shot_order != order:
            row.shot_order = order
            row.updated_at = utcnow()
            session.add(row)
        order += 1
    session.commit()
    return list_shots(session, scene_id)


def delete_shot(session: Session, shot_id: str) -> None:
    shot = session.get(Shot, shot_id)
    if shot is None:
        raise NotFoundError(f"shot {shot_id} not found")
    session.delete(shot)
    session.commit()


def delete_scene(session: Session, scene_id: str) -> int:
    """Delete a scene and its shots; render history is kept. Returns shots deleted."""
    scene = get_scene(session, scene_id)
    shots = session.exec(select(Shot).where(Shot.scene_id == scene_id)).all()
    for shot in shots:
        session.delete(shot)
    session.delete(scene)
    session.commit()
    return len(shots)


def list_shots(session: Session, scene_id: str) -> list[Shot]:
    return list(
        session.exec(select(Shot).where(Shot.scene_id == scene_id).order_by(Shot.shot_order)).all()
    )


def diff_fields(current: dict, incoming: dict) -> dict:
    """Subset of *current* whose keys appear in *incoming* with a DIFFERENT,
    non-None value — i.e. the old values an update is about to overwrite.

    Known limitation: a field whose PREVIOUS value was None is stored as None
    here, and reverting it is a no-op because update_scene/update_shot treat
    None kwargs as "leave unchanged"."""
    return {
        k: current[k]
        for k, v in incoming.items()
        if v is not None and k in current and current[k] != v
    }


REVISION_KEEP = 20


def _record_revision(
    session: Session, entity_type: str, entity_id: str, changed: dict, source: str
) -> None:
    """Persist one revision row holding the pre-update values, then prune the
    entity's history beyond the most recent REVISION_KEEP rows.

    Adds to the session without committing — the caller's update commit
    persists the revision atomically with the change itself."""
    session.add(
        Revision(
            entity_type=entity_type,
            entity_id=entity_id,
            fields_json=changed,
            source=source,
        )
    )
    session.flush()  # make the new row visible to the pruning query below
    stale = session.exec(
        select(Revision)
        .where(Revision.entity_type == entity_type, Revision.entity_id == entity_id)
        .order_by(Revision.created_at.desc(), Revision.id.desc())  # type: ignore[attr-defined]
        .offset(REVISION_KEEP)
    ).all()
    for row in stale:
        session.delete(row)


def update_scene(
    session: Session,
    scene_id: str,
    *,
    title: str | None = None,
    summary: str | None = None,
    duration: int | None = None,
    aspect_ratio: str | None = None,
    character_ids: list[str] | None = None,
    asset_ids: list[str] | None = None,
    source: str = "edit",
) -> Scene:
    scene = get_scene(session, scene_id)
    changed = diff_fields(
        {
            "title": scene.title,
            "summary": scene.summary,
            "duration": scene.duration,
            "aspect_ratio": scene.aspect_ratio,
            "character_ids": list(scene.character_ids_json or []),
            "asset_ids": list(scene.asset_ids_json or []),
        },
        {
            "title": title,
            "summary": summary,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "character_ids": character_ids,
            "asset_ids": asset_ids,
        },
    )
    if changed:
        _record_revision(session, "scene", scene.id, changed, source)
    if title is not None:
        scene.title = title
    if summary is not None:
        scene.summary = summary
    if duration is not None:
        scene.duration = duration
    if aspect_ratio is not None:
        scene.aspect_ratio = aspect_ratio
    if character_ids is not None:
        scene.character_ids_json = character_ids
    if asset_ids is not None:
        scene.asset_ids_json = asset_ids
    scene.updated_at = utcnow()
    session.add(scene)
    session.commit()
    _auto_link(session, scene.id)
    session.refresh(scene)
    return scene


def update_shot(
    session: Session,
    shot_id: str,
    *,
    prompt: str | None = None,
    duration: int | None = None,
    camera: str | None = None,
    movement: str | None = None,
    asset_ids: list[str] | None = None,
    shot_order: int | None = None,
    source: str = "edit",
) -> Shot:
    shot = session.get(Shot, shot_id)
    if shot is None:
        raise NotFoundError(f"shot {shot_id} not found")
    changed = diff_fields(
        {
            "prompt": shot.prompt,
            "duration": shot.duration,
            "camera": shot.camera,
            "movement": shot.movement,
            "asset_ids": list(shot.asset_ids_json or []),
            "shot_order": shot.shot_order,
        },
        {
            "prompt": prompt,
            "duration": duration,
            "camera": camera,
            "movement": movement,
            "asset_ids": asset_ids,
            "shot_order": shot_order,
        },
    )
    if changed:
        _record_revision(session, "shot", shot.id, changed, source)
    if prompt is not None:
        shot.prompt = prompt
    if duration is not None:
        shot.duration = duration
    if camera is not None:
        shot.camera = camera
    if movement is not None:
        shot.movement = movement
    if asset_ids is not None:
        shot.asset_ids_json = asset_ids
    if shot_order is not None:
        shot.shot_order = shot_order
    shot.updated_at = utcnow()
    session.add(shot)
    session.commit()
    _auto_link(session, shot.scene_id)
    session.refresh(shot)
    return shot


def list_revisions(
    session: Session, entity_type: str, entity_id: str, limit: int = 20
) -> list[Revision]:
    """The entity's revision trail, newest first. 404 when the entity is gone."""
    if entity_type == "scene":
        get_scene(session, entity_id)
    elif entity_type == "shot" and session.get(Shot, entity_id) is None:
        raise NotFoundError(f"shot {entity_id} not found")
    return list(
        session.exec(
            select(Revision)
            .where(Revision.entity_type == entity_type, Revision.entity_id == entity_id)
            .order_by(Revision.created_at.desc(), Revision.id.desc())  # type: ignore[attr-defined]
            .limit(limit)
        ).all()
    )


def revert_revision(session: Session, revision_id: str) -> Scene | Shot:
    """Apply a revision's stored old values back onto its entity.

    Goes through update_scene/update_shot, so the pre-revert state is itself
    recorded as a new revision (source "revert") — reverts are undoable."""
    revision = session.get(Revision, revision_id)
    if revision is None:
        raise NotFoundError(f"revision {revision_id} not found")
    if revision.entity_type == "scene":
        return update_scene(
            session, revision.entity_id, source="revert", **revision.fields_json
        )
    return update_shot(
        session, revision.entity_id, source="revert", **revision.fields_json
    )


def add_cast_member(session: Session, scene_id: str, character_id: str) -> Scene:
    scene = get_scene(session, scene_id)
    if session.get(Character, character_id) is None:
        raise NotFoundError(f"character {character_id} not found")
    ids = list(scene.character_ids_json or [])
    if character_id not in ids:
        scene.character_ids_json = [*ids, character_id]
        scene.updated_at = utcnow()
        session.add(scene)
        session.commit()
        session.refresh(scene)
    return scene


def remove_cast_member(session: Session, scene_id: str, character_id: str) -> Scene:
    scene = get_scene(session, scene_id)
    ids = list(scene.character_ids_json or [])
    if character_id in ids:
        scene.character_ids_json = [i for i in ids if i != character_id]
        scene.updated_at = utcnow()
        session.add(scene)
        session.commit()
        session.refresh(scene)
    return scene


def attach_shot_asset(session: Session, shot_id: str, asset_id: str) -> Shot:
    shot = session.get(Shot, shot_id)
    if shot is None:
        raise NotFoundError(f"shot {shot_id} not found")
    if session.get(Asset, asset_id) is None:
        raise NotFoundError(f"asset {asset_id} not found")
    ids = list(shot.asset_ids_json or [])
    if asset_id not in ids:
        shot.asset_ids_json = [*ids, asset_id]
        shot.updated_at = utcnow()
        session.add(shot)
        session.commit()
        session.refresh(shot)
    return shot


def detach_shot_asset(session: Session, shot_id: str, asset_id: str) -> Shot:
    shot = session.get(Shot, shot_id)
    if shot is None:
        raise NotFoundError(f"shot {shot_id} not found")
    ids = list(shot.asset_ids_json or [])
    if asset_id in ids:
        shot.asset_ids_json = [i for i in ids if i != asset_id]
        shot.updated_at = utcnow()
        session.add(shot)
        session.commit()
        session.refresh(shot)
    return shot
