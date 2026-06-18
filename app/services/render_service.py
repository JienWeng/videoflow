"""Render service — where AI-produced JSON (RenderSpec) meets the provider.

This is the only place agents and providers converge. It resolves reference
assets to URLs, builds the Kling payload, submits the job (so submit errors
surface immediately), persists a RenderJob, and enqueues background polling.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlmodel import Session, select

from app.agents.prompt_agent import (
    NO_CLONE_NEGATIVE,
    NO_TEXT_NEGATIVE,
    cap_references,
    collect_named_references,
    enforce_render_defaults,
    voice_line,
)
from app.config import get_settings
from app.errors import NotFoundError, ValidationFailedError
from app.jobs import worker
from app.models import Asset, Character, RenderJob, RenderOutput, RenderStatus, Scene
from app.models.base import new_id, utcnow
from app.providers.atlascloud_client import get_atlas_client
from app.providers.registry import get_video_provider
from app.providers.url_resolver import AtlasCloudUploadResolver
from app.schemas import ReferenceImage, RenderSpec, StoryboardShot
from app.services.dialogue import has_dialogue
from app.services import project_service

logger = logging.getLogger(__name__)

# Name of the previous-scene anchor frame reference (@-token in the prompt).
ANCHOR_NAME = "上一场景"

# Locale codes -> human-readable names for the prompt. The resolver may yield a
# bare locale code (e.g. 'zh' from config defaults); the video prompt reads more
# naturally as "Spoken dialogue in Chinese" than "...in zh". Unknown values pass
# through verbatim (already-human values like 'English' stay as-is).
_DIALOGUE_LANGUAGE_NAMES = {
    "zh": "Chinese",
    "zh-cn": "Chinese",
    "zh-hans": "Chinese",
    "en": "English",
    "en-us": "English",
}


def _humanize_language(value: str) -> str:
    """Map a common locale code to its English name; pass anything else through."""
    return _DIALOGUE_LANGUAGE_NAMES.get((value or "").strip().lower(), value)


def resolve_dialogue_language(session: Session) -> str:
    """The effective spoken-dialogue language for a render, via the settings
    resolver (project override -> global -> config default). Used by BOTH render
    paths so the language of 「」 lines is configurable, not hardcoded.

    A bare locale code (e.g. 'zh') is humanized to its English name ('Chinese')
    so the prompt reads naturally; already-human values pass through unchanged."""
    from app.services import settings_service

    value = settings_service.resolve(
        session,
        "dialogue_language",
        default="English",
        project_id=project_service.active_project_id(session),
    )
    return _humanize_language(value)


def resolve_render_negatives(session: Session) -> tuple[str, str, list[str]]:
    """Resolver-backed negative-prompt fragments for a render:
    (no_text_negative, no_clone_negative, extra_negatives).

    The first two keep the prompt-agent defaults (NO_TEXT_NEGATIVE /
    NO_CLONE_NEGATIVE) unless overridden via app settings keys
    'no_text_negative' / 'no_clone_negative'; `extra_negatives` is the
    render_negatives list (resolver-backed, empty by default)."""
    from app.services import settings_service

    pid = project_service.active_project_id(session)
    no_text = settings_service.get_app_setting(
        session, "no_text_negative", NO_TEXT_NEGATIVE, scope="global"
    ) or NO_TEXT_NEGATIVE
    no_clone = settings_service.get_app_setting(
        session, "no_clone_negative", NO_CLONE_NEGATIVE, scope="global"
    ) or NO_CLONE_NEGATIVE
    extras = settings_service.resolve(
        session, "render_negatives", default=[], project_id=pid
    ) or []
    return no_text, no_clone, list(extras)


def pick_previous_scene(current: Scene, scenes: list[Scene]) -> Scene | None:
    """The scene rendered 'before' `current`: same script (when current has a
    script_id) with the largest created_at strictly less than current's;
    without a script_id, the same rule over all scenes. None for the first
    or a loner scene."""
    pool = (
        [s for s in scenes if s.script_id == current.script_id]
        if current.script_id
        else list(scenes)
    )
    candidates = [
        s for s in pool if s.id != current.id and s.created_at < current.created_at
    ]
    return max(candidates, key=lambda s: (s.created_at, s.id)) if candidates else None


def _latest_succeeded_output(session: Session, scene_id: str) -> RenderOutput | None:
    """Newest RenderOutput (raw video, not captioned) of the scene's newest
    succeeded render job that actually has a video on disk."""
    jobs = session.exec(
        select(RenderJob)
        .where(RenderJob.scene_id == scene_id, RenderJob.status == RenderStatus.succeeded)
        .order_by(RenderJob.created_at.desc())  # type: ignore[attr-defined]
    ).all()
    for job in jobs:
        outputs = session.exec(
            select(RenderOutput)
            .where(RenderOutput.render_job_id == job.id)
            .order_by(RenderOutput.created_at.desc())  # type: ignore[attr-defined]
        ).all()
        for output in outputs:
            if output.video_path:
                return output
    return None


def _existing_anchor_asset(session: Session, scene_id: str) -> Asset | None:
    rows = session.exec(
        select(Asset).where(Asset.type == "frame").order_by(Asset.created_at.desc())  # type: ignore[attr-defined]
    ).all()
    for asset in rows:
        meta = asset.metadata_json or {}
        if meta.get("anchor") and meta.get("scene_id") == scene_id:
            return asset
    return None


async def _anchor_reference(session: Session, scene: Scene) -> dict | None:
    """Frame anchoring: the LAST FRAME of the previous scene's latest successful
    render becomes a named reference, chaining the actually-rendered look
    (lighting, grading, character appearance) across scenes.

    Idempotent per (scene, source output): the existing anchor Asset is reused
    while the source output is unchanged; a newer render produces a new frame
    file + Asset and relinks (the old anchor stays in the library, harmless).
    Returns {"name": ANCHOR_NAME, "asset_id": ...} or None (no previous scene,
    no successful render, or no ffmpeg)."""
    from app.services import media

    pool = [
        s for s in session.exec(select(Scene)).all()
        if s.project_id == scene.project_id
    ]
    prev = pick_previous_scene(scene, pool)
    if prev is None:
        return None
    output = _latest_succeeded_output(session, prev.id)
    if output is None:
        return None

    existing = _existing_anchor_asset(session, scene.id)
    if existing and (existing.metadata_json or {}).get("source_output_id") == output.id:
        return {"name": ANCHOR_NAME, "asset_id": existing.id}

    settings = get_settings()
    settings.ensure_dirs()
    asset_id = new_id("asset")
    frame = await media.extract_last_frame(
        Path(output.video_path), settings.assets_dir / f"{asset_id}.png"
    )
    if frame is None:
        return None
    asset = Asset(
        id=asset_id,
        project_id=scene.project_id,
        type="frame",
        name=ANCHOR_NAME,
        file_path=str(frame),
        metadata_json={
            "scene_id": scene.id,
            "source_output_id": output.id,
            "anchor": True,
        },
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return {"name": ANCHOR_NAME, "asset_id": asset.id}


def _scene_bibles(session: Session, scene_id: str | None):
    from app.services import scene_service

    if not scene_id:
        return []
    scene = session.get(Scene, scene_id)
    if scene is None:
        return []
    return [
        scene_service.character_to_bible(c)
        for cid in (scene.character_ids_json or [])
        if (c := session.get(Character, cid))
    ]


async def _precheck_spec(session: Session, spec: RenderSpec) -> RenderSpec:
    """Cheap text self-critique BEFORE the paid render (gated by precheck_enabled,
    fail-open). Applies any prompt revision to a COPY, re-asserts the render
    invariants, and re-validates; the original spec is rendered if anything goes
    wrong, so the critic can never block or corrupt a render."""
    from app.services import settings_service, style_service

    if not settings_service.resolve(
        session, "precheck_enabled", default=get_settings().precheck_enabled
    ):
        return spec
    try:
        from app.agents import spec_critic_agent

        crit = await spec_critic_agent.critique_spec(
            spec=spec,
            style=style_service.style_context(style_service.get_style(session)),
        )
        if crit.ok or (not crit.revised_prompt and not crit.revised_multi_prompt):
            return spec
        candidate = RenderSpec.model_validate(spec.model_dump(mode="json"))
        if crit.revised_prompt:
            candidate.prompt = crit.revised_prompt
        if crit.revised_multi_prompt and len(crit.revised_multi_prompt) == len(
            candidate.multi_prompt
        ):
            candidate.multi_prompt = crit.revised_multi_prompt
        enforce_render_defaults(
            candidate,
            named_references=[
                {"name": r.name, "asset_id": r.asset_id}
                for r in candidate.reference_images
            ],
            character_bibles=_scene_bibles(session, candidate.scene_id),
        )
        RenderSpec.model_validate(candidate.model_dump(mode="json"))
        logger.info("spec precheck revised the prompt for scene %s", spec.scene_id)
        return candidate
    except Exception:
        logger.exception("spec precheck failed; rendering the original spec")
        return spec


async def start_render(session: Session, spec: RenderSpec) -> RenderJob:
    spec = await _precheck_spec(session, spec)
    provider = get_video_provider(spec)
    resolver = AtlasCloudUploadResolver(session, get_atlas_client())

    payload = await provider.build_payload(spec, resolver)
    provider_job_id = await provider.submit(payload)

    project_id = None
    if spec.scene_id and (job_scene := session.get(Scene, spec.scene_id)):
        project_id = job_scene.project_id
    if project_id is None:
        project_id = project_service.active_project_id(session)

    job = RenderJob(
        project_id=project_id,
        scene_id=spec.scene_id,
        shot_id=spec.shot_id,
        provider=spec.provider,
        model=spec.model,
        provider_job_id=provider_job_id,
        status=RenderStatus.pending,
        # Provider payload plus the originating spec, so QA-driven retries can
        # rebuild and resubmit the exact RenderSpec (asset ids, not URLs).
        request_json={**payload, "spec": spec.model_dump(mode="json")},
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    worker.enqueue(job.id)
    return job


async def render_scene(
    session: Session,
    scene_id: str,
    *,
    dialogue_language: str | None = None,
    style_extra: str | None = None,
) -> RenderJob:
    """Deterministic whole-scene render: stored shots become the multi-shot
    storyboard (customize, indexed), and every linked reference — characters'
    images, scene/shot assets and the scene's 分镜图 — feeds Kling images[].

    `dialogue_language` / `style_extra` override the project defaults for THIS
    render (used by the autopilot's per-run orientation/language/style config)."""
    from app.services import scene_service, storyboard_service, style_service

    scene = scene_service.get_scene(session, scene_id)
    shots = scene_service.list_shots(session, scene_id)
    if not shots:
        raise ValidationFailedError(
            f"scene {scene_id} has no shots — generate shots before rendering"
        )
    total = sum(max(1, s.duration) for s in shots)
    if not 3 <= total <= 15:
        raise ValidationFailedError(
            f"scene duration {total}s outside the provider's 3-15s range — "
            "adjust shot durations or split the scene"
        )

    bibles = [
        scene_service.character_to_bible(c)
        for cid in scene.character_ids_json or []
        if (c := session.get(Character, cid))
    ]
    asset_ids = list(scene.asset_ids_json or [])
    for shot in shots:
        asset_ids.extend(shot.asset_ids_json or [])
    # Tolerance / self-healing: ids without an Asset row (e.g. hallucinated ids
    # persisted before resolve_entity_ids existed) are skipped — a missing prop
    # must never 404 a whole render.
    known_ids = []
    for aid in asset_ids:
        if session.get(Asset, aid) is not None:
            known_ids.append(aid)
        else:
            logger.warning(
                "skipping unknown asset id %s while rendering scene %s", aid, scene_id
            )
    asset_ids = known_ids
    asset_names = {
        aid: a.name for aid in asset_ids
        if (a := session.get(Asset, aid)) and a.name
    }
    # Reference priority groups for the live Kling cap (ret:1201 above
    # settings.atlas_video_max_refs): characters > 分镜图 storyboard >
    # 上一场景 frame anchor > scene/shot prop assets. Characters and props are
    # collected in TWO passes of collect_named_references — the second pass
    # repeats the bibles so the dedup / clone-name-collision rules stay exactly
    # as before, then the character entries are stripped back out by asset id,
    # leaving only the prop refs.
    char_refs = collect_named_references(
        named_references=[],
        character_bibles=bibles,
        shot_asset_ids=[],
        asset_names={},
    )
    char_ref_ids = {r["asset_id"] for r in char_refs}
    prop_refs = [
        r
        for r in collect_named_references(
            named_references=[],
            character_bibles=bibles,
            shot_asset_ids=asset_ids,
            asset_names=asset_names,
        )
        if r["asset_id"] not in char_ref_ids
    ]
    seen_ids = char_ref_ids | {r["asset_id"] for r in prop_refs}
    # Every shot is supposed to speak (one 「」 line); warn but never block.
    for shot in shots:
        if not has_dialogue(shot.prompt):
            logger.warning(
                "shot %s (order %s) of scene %s has no 「」 spoken line — "
                "it will render silent",
                shot.id, shot.shot_order, scene_id,
            )

    limit = get_settings().atlas_video_max_refs
    storyboard = storyboard_service.latest_storyboard_for_scene(session, scene_id)
    storyboard_refs = (
        [{"name": "分镜图", "asset_id": storyboard.id}]
        if storyboard and storyboard.id not in seen_ids
        else []
    )

    # Frame anchoring: the previous scene's final rendered frame. Only fetched
    # when it could survive the cap (it outranks props, so only characters +
    # storyboard can crowd it out — never extract a frame we'd just drop).
    # Best-effort — anchoring must never fail the render.
    anchor_refs: list[dict] = []
    try:
        if len(char_refs) + len(storyboard_refs) < limit:
            anchor = await _anchor_reference(session, scene)
            if anchor and anchor["asset_id"] not in seen_ids:
                anchor_refs = [anchor]
    except Exception:
        logger.exception(
            "frame anchoring failed for scene %s; rendering without the anchor",
            scene_id,
        )

    refs = cap_references([char_refs, storyboard_refs, anchor_refs, prop_refs], limit)
    kept_ids = {r["asset_id"] for r in refs}
    # Mention @分镜图/@上一场景 in the prompt ONLY when their reference
    # actually survived the cap — a token without its image confuses Kling.
    storyboard_kept = storyboard is not None and storyboard.id in kept_ids
    anchored = bool(anchor_refs) and anchor_refs[0]["asset_id"] in kept_ids

    # Deterministic voice direction from the cast's voice_rules, placed before
    # the negatives so every render of this cast uses the same voices.
    voices = voice_line(bibles)
    # Resolver-backed dialogue language + negatives (configurable per project),
    # with an optional per-run language override (humanized: 'zh' -> 'Chinese').
    dialogue_language = (
        _humanize_language(dialogue_language)
        if dialogue_language
        else resolve_dialogue_language(session)
    )
    no_text, no_clone, extra_negatives = resolve_render_negatives(session)
    extra_neg = (", " + ", ".join(extra_negatives)) if extra_negatives else ""
    prompt = (
        f"{scene.summary}. "
        + ("Follow the @分镜图 storyboard panels in order for composition, scene "
           "continuity and lighting. " if storyboard_kept else "")
        + (f"Match the lighting, color grading and character appearance of "
           f"@{ANCHOR_NAME} (the previous scene's final frame). " if anchored else "")
        + f"Spoken dialogue in {dialogue_language}, clear and natural. "
        + (f"{voices}. " if voices else "")
        + "Negative: "
        f"{no_text}, no watermark, no outfit changes, no extra "
        f"characters, no distorted faces, {no_clone}{extra_neg}."
    )
    # Deterministic style enforcement on the whole-scene video prompt, plus an
    # optional per-run custom style note (applied to just this render).
    prompt = style_service.apply_style(prompt, style_service.get_style(session))
    if style_extra:
        prompt = f"{prompt} Additional style for this video: {style_extra}."
    spec = RenderSpec(
        scene_id=scene.id,
        duration=total,
        aspect_ratio=scene.aspect_ratio,
        prompt=prompt,
        reference_images=[ReferenceImage(**r) for r in refs],
        sound=True,
        keep_original_sound=True,
        multi_shot=True,
        shot_type="customize",
        multi_prompt=[
            StoryboardShot(prompt=s.prompt, duration=max(1, s.duration)) for s in shots
        ],
    )
    return await start_render(session, spec)


# Marks (and locates) the corrective suffix appended by retry_output, so a
# retry of a retry replaces it instead of stacking suffixes.
CORRECTIONS_MARKER = "Corrections from review:"
MAX_CORRECTION_ISSUES = 5


def apply_render_patch(spec: RenderSpec, patch) -> RenderSpec:
    """Apply a RenderSpecPatch field-by-field (pure; mutates and returns `spec`).

    Only touches what the vision reviser named: the main prompt, individual
    multi_prompt entries (1-based, out-of-range ignored), and EXISTING references
    (swap asset / remove). A reference op whose name isn't already present is
    ignored — never introduce a new character name (Kling would render a clone).
    The <=7 reference cap and voice/sound/negatives are re-asserted by the caller
    via enforce_render_defaults; this function does not change reference count
    except by removal."""
    if patch.main_prompt:
        spec.prompt = patch.main_prompt
    if patch.aspect_ratio:
        spec.aspect_ratio = patch.aspect_ratio
    for sp in patch.shot_prompts:
        idx = sp.index - 1
        if 0 <= idx < len(spec.multi_prompt):
            spec.multi_prompt[idx].prompt = sp.prompt
    if patch.references:
        by_name = {r.name: r for r in spec.reference_images}
        keep: list[ReferenceImage] = []
        removed = {
            rp.name for rp in patch.references
            if rp.op == "remove" and rp.name in by_name
        }
        swaps = {
            rp.name: rp.asset_id
            for rp in patch.references
            if rp.op == "swap" and rp.name in by_name and rp.asset_id
        }
        for ref in spec.reference_images:
            if ref.name in removed:
                continue
            if ref.name in swaps:
                ref.asset_id = swaps[ref.name]
            keep.append(ref)
        spec.reference_images = keep
    return spec


async def retry_output(session: Session, output_id: str) -> RenderJob:
    """Submit a corrective re-render for a QA'd output.

    Rebuilds the original job's RenderSpec (stored under request_json["spec"])
    and appends the QA issues to the main prompt as
    ' Corrections from review: <issue1>; <issue2>.' — multi_prompt entries stay
    as authored. Any previous corrections suffix is stripped first, so only the
    LATEST QA issues are carried. Manual trigger only; renders cost money.
    """
    output = session.get(RenderOutput, output_id)
    if output is None:
        raise NotFoundError(f"output {output_id} not found")
    job = session.get(RenderJob, output.render_job_id)
    if job is None:
        raise NotFoundError(f"render job {output.render_job_id} not found")

    issues = [
        text for i in (output.qa_json or {}).get("issues") or []
        if (text := str(i).strip())
    ]
    if not issues:
        raise ValidationFailedError(
            f"output {output_id} has no QA issues recorded — nothing to correct"
        )

    spec_dict = (job.request_json or {}).get("spec")
    if not spec_dict:
        raise ValidationFailedError(
            f"job {job.id} did not store its render spec — cannot rebuild it for a retry"
        )
    spec = RenderSpec.model_validate(spec_dict)

    base = spec.prompt.split(CORRECTIONS_MARKER, 1)[0].rstrip()
    corrections = "; ".join(issues[:MAX_CORRECTION_ISSUES])
    spec.prompt = f"{base} {CORRECTIONS_MARKER} {corrections}."

    logger.info("corrective re-render for output %s (job %s)", output_id, job.id)
    return await start_render(session, spec)


async def revise_output(session: Session, output_id: str) -> RenderJob:
    """Targeted corrective re-render: a vision reviser SEES the flawed frames +
    references and emits a RenderSpecPatch applied field-by-field (rewrite the
    offending shot, swap/strengthen a drifted character's EXISTING reference),
    then the invariants are re-asserted (voice/sound/negatives + <=7 ref cap) and
    the spec is re-validated. Falls back to the blind suffix retry on any failure
    or when targeted revise is disabled — strictly additive."""
    from app.services import settings_service

    if not settings_service.resolve(
        session, "targeted_revise_enabled",
        default=get_settings().targeted_revise_enabled,
    ):
        return await retry_output(session, output_id)

    output = session.get(RenderOutput, output_id)
    if output is None:
        raise NotFoundError(f"output {output_id} not found")
    job = session.get(RenderJob, output.render_job_id)
    if job is None:
        raise NotFoundError(f"render job {output.render_job_id} not found")
    spec_dict = (job.request_json or {}).get("spec")
    if not spec_dict:
        return await retry_output(session, output_id)

    try:
        from app.agents import spec_reviser_agent
        from app.services import media, qa_service

        spec = RenderSpec.model_validate(spec_dict)
        frames: list = []
        if output.video_path and Path(output.video_path).exists():
            fdir = get_settings().outputs_dir / (job.scene_id or "misc") / f"{job.id}_revise"
            frames = await media.extract_frames(Path(output.video_path), fdir, max_frames=4)
        refs = qa_service._reference_image_paths(session, job)
        qa = output.qa_json or {}
        patch = await spec_reviser_agent.revise_spec(
            spec=spec,
            qa_result=qa,
            frames=[str(f) for f in frames],
            reference_images=refs,
            target=qa.get("worst_dimension"),
        )
        apply_render_patch(spec, patch)
        enforce_render_defaults(
            spec,
            named_references=[
                {"name": r.name, "asset_id": r.asset_id} for r in spec.reference_images
            ],
            character_bibles=_scene_bibles(session, job.scene_id),
        )
        RenderSpec.model_validate(spec.model_dump(mode="json"))
        limit = get_settings().atlas_video_max_refs
        if len(spec.reference_images) > limit:
            raise ValueError(f"{len(spec.reference_images)} refs exceed cap {limit}")
        logger.info("targeted revise for output %s (job %s)", output_id, job.id)
        return await start_render(session, spec)
    except Exception:
        logger.exception(
            "targeted revise failed for %s; falling back to blind retry", output_id
        )
        try:
            return await retry_output(session, output_id)
        except Exception:
            # Blind retry needs recorded QA issues; if there are none, don't fail
            # the run — just resubmit the original spec for another take.
            logger.exception(
                "blind retry also failed for %s; resubmitting original spec", output_id
            )
            return await start_render(session, RenderSpec.model_validate(spec_dict))


def _slugify(text: str, *, max_len: int = 60) -> str:
    """A filesystem/Content-Disposition-safe slug.

    Keeps CJK and alphanumerics (Chinese scene titles are common here), turns
    runs of spaces/punctuation into single hyphens, trims to max_len. Empty input
    yields '' so the caller can fall back to the output id."""
    import re

    # \w is Unicode-aware in Python 3 str patterns, so CJK (Chinese scene titles)
    # is preserved; everything else collapses to single hyphens.
    slug = re.sub(r"[^\w-]+", "-", text).strip("-")
    return slug[:max_len].strip("-")


def download_filename(session: Session, output: RenderOutput, variant: str) -> str:
    """A friendly download filename: '<scene-title>-<output-id>[-captioned].mp4'.

    Falls back to the output id alone when the scene has no title (or the job
    isn't tied to a scene). The output id keeps the name unique across takes."""
    title = ""
    job = session.get(RenderJob, output.render_job_id)
    if job and job.scene_id:
        scene = session.get(Scene, job.scene_id)
        if scene and scene.title:
            title = scene.title
    slug = _slugify(title)
    stem = f"{slug}-{output.id}" if slug else output.id
    if variant == "captioned":
        stem = f"{stem}-captioned"
    return f"{stem}.mp4"


def download_path(output: RenderOutput, variant: str) -> Path:
    """The on-disk path for the requested variant (raw | captioned).

    Raises NotFoundError when the requested file is missing (e.g. captioned was
    asked for but the output was never captioned, or the raw file is gone)."""
    if variant not in ("raw", "captioned"):
        raise ValidationFailedError(
            f"unknown download variant '{variant}' (use raw|captioned)"
        )
    path_str = output.captioned_path if variant == "captioned" else output.video_path
    if not path_str:
        raise NotFoundError(
            f"output {output.id} has no {variant} video"
        )
    path = Path(path_str)
    if not path.exists():
        raise NotFoundError(f"output {output.id} {variant} video file is missing")
    return path


def get_output(session: Session, output_id: str) -> RenderOutput:
    output = session.get(RenderOutput, output_id)
    if output is None:
        raise NotFoundError(f"output {output_id} not found")
    return output


async def resubmit_job(session: Session, job_id: str) -> RenderJob:
    """Resubmit a job's stored RenderSpec verbatim (no QA corrections).

    The primary use is recovering a FAILED job: the original request is rebuilt
    from request_json['spec'] and submitted again unchanged. Unlike retry_output
    (which folds QA issues into the prompt and needs a successful, scored output),
    this works straight off the job and never mutates the prompt — handy when the
    failure was transient (a gateway 5xx, a timeout) rather than a content issue.
    """
    job = get_job(session, job_id)
    spec_dict = (job.request_json or {}).get("spec")
    if not spec_dict:
        raise ValidationFailedError(
            f"job {job.id} did not store its render spec — cannot resubmit it"
        )
    spec = RenderSpec.model_validate(spec_dict)
    logger.info("resubmitting job %s (status was %s)", job.id, job.status)
    return await start_render(session, spec)


async def run_qa_for_output(session: Session, output_id: str) -> RenderOutput:
    """Score an output that hasn't been QA'd yet (or whose QA crashed).

    Unlocks the Fix & re-render flow: retry_output needs recorded QA issues, so an
    output produced when the QA agent was unavailable can be scored on demand.
    Re-running on an already-scored output is allowed (re-review)."""
    from app.services import qa_service

    output = session.get(RenderOutput, output_id)
    if output is None:
        raise NotFoundError(f"output {output_id} not found")
    if not output.video_path or not Path(output.video_path).exists():
        raise ValidationFailedError(
            f"output {output_id} has no video file on disk to review"
        )
    job = get_job(session, output.render_job_id)
    return await qa_service.run_qa(session, job, output, Path(output.video_path))


def select_output(session: Session, output_id: str, selected: bool = True) -> RenderOutput:
    """Mark an output as the selected take for its render job.

    Selecting one output deselects every other output of the SAME job, so a job
    has at most one selected take (the human's chosen take among retries)."""
    output = session.get(RenderOutput, output_id)
    if output is None:
        raise NotFoundError(f"output {output_id} not found")
    if selected:
        for other in session.exec(
            select(RenderOutput).where(
                RenderOutput.render_job_id == output.render_job_id,
                RenderOutput.id != output.id,
            )
        ).all():
            if other.selected:
                other.selected = False
                other.updated_at = utcnow()
                session.add(other)
    output.selected = selected
    output.updated_at = utcnow()
    session.add(output)
    session.commit()
    session.refresh(output)
    return output


def get_job(session: Session, job_id: str) -> RenderJob:
    job = session.get(RenderJob, job_id)
    if job is None:
        raise NotFoundError(f"render job {job_id} not found")
    return job


def list_jobs(session: Session) -> list[RenderJob]:
    pid = project_service.active_project_id(session)
    return list(
        session.exec(select(RenderJob).where(RenderJob.project_id == pid)).all()
    )


def job_outputs(session: Session, job_id: str) -> list[RenderOutput]:
    return list(
        session.exec(select(RenderOutput).where(RenderOutput.render_job_id == job_id)).all()
    )
