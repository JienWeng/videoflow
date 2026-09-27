"""Project service — the server-side ACTIVE project that scopes everything.

Single-user, local-first: exactly one project is active at a time and every
list/create path in the other services scopes to it implicitly via
`get_active` / `active_project_id`. Existing endpoint signatures never change.

Migration strategy: `get_active` is LAZY and idempotent — on a database with
no projects it creates the default "My project" and adopts every orphan row
(project_id NULL in the six project-owned tables). This single code path is
both the live-DB migration and the test-fixture path (fixtures seed rows with
project_id NULL and never call init_db).

Known v1 limits (intentional):
- Direct-by-id access (session.get / GET /scenes/{id} etc.) is NOT
  project-checked — cross-project access by explicit id stays possible, and
  renders referencing old ids keep working.
- Ops (the activity tray) stay global; they are transient bookkeeping.
"""

from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path

from sqlalchemy import update
from sqlmodel import Session, col, func, select

from app.config import get_settings
from app.errors import NotFoundError, ValidationFailedError
from app.models import (
    Asset,
    Character,
    Op,
    Project,
    RenderJob,
    RenderOutput,
    Scene,
    Script,
    Shot,
    StyleGuide,
)
from app.models.base import new_id, utcnow

# Every table owned by a project (the six scope columns).
PROJECT_OWNED = (Character, Asset, Scene, Script, StyleGuide, RenderJob)


def adopt_orphans(session: Session, project: Project) -> int:
    """Backfill every row with project_id NULL into *project*. Idempotent.

    Returns the number of adopted rows. Commits."""
    adopted = 0
    for model in PROJECT_OWNED:
        result = session.execute(
            update(model)
            .where(col(model.project_id).is_(None))  # type: ignore[arg-type]
            .values(project_id=project.id)
        )
        adopted += result.rowcount or 0
    if adopted:
        session.commit()
    return adopted


def get_active(session: Session) -> Project:
    """Return the active project, lazily bootstrapping the workspace.

    - No projects at all -> create the default "My project" (active).
    - Projects exist but none is active -> activate the oldest.
    - While there is exactly ONE project, orphan rows (project_id NULL) are
      swept into it — so data seeded outside the scoped create paths (old
      databases, test fixtures) is transparently adopted.
    """
    projects = list(session.exec(select(Project)).all())
    active = next((p for p in projects if p.is_active), None)
    if active is None:
        if projects:
            active = min(projects, key=lambda p: (p.created_at, p.id))
            active.is_active = True
            active.updated_at = utcnow()
            session.add(active)
            session.commit()
            session.refresh(active)
        else:
            active = Project(is_active=True)
            session.add(active)
            session.commit()
            session.refresh(active)
    if len(projects) <= 1 and adopt_orphans(session, active):
        # The adoption commit expires the instance; reload it so callers
        # (and pydantic's model_dump) see populated fields.
        session.refresh(active)
    return active


def active_project_id(session: Session) -> str:
    """The active project's id — the scoping helper every service uses."""
    return get_active(session).id


def list_projects(session: Session) -> list[Project]:
    # Ensure the default project exists before listing.
    get_active(session)
    return list(
        session.exec(
            select(Project).order_by(Project.created_at, Project.id)  # type: ignore[arg-type]
        ).all()
    )


def get_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"project {project_id} not found")
    return project


def create_project(session: Session, *, name: str, description: str = "") -> Project:
    """Create a new (inactive) project. Callers that want to switch into it
    activate it explicitly (the POST /projects endpoint does both)."""
    # Bootstrap first so existing orphan data is adopted by the DEFAULT
    # project, never by a project created later.
    get_active(session)
    project = Project(name=name, description=description)
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def activate(session: Session, project_id: str) -> Project:
    """Make *project_id* the single active project (clears all other flags)."""
    project = get_project(session, project_id)
    active = get_active(session)
    if project.id != active.id:
        running_generation = session.exec(
            select(Op).where(
                Op.kind == "video_generation",
                Op.status == "running",
                (Op.project_id == active.id) | (Op.project_id.is_(None)),
            )
        ).first()
        if running_generation is not None:
            raise ValidationFailedError(
                "cannot switch projects while video generation is still running"
            )
    for other in session.exec(select(Project).where(Project.is_active)).all():
        if other.id != project.id:
            other.is_active = False
            other.updated_at = utcnow()
            session.add(other)
    if not project.is_active:
        project.is_active = True
        project.updated_at = utcnow()
        session.add(project)
    session.commit()
    session.refresh(project)
    return project


def update_project(
    session: Session,
    project_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Project:
    """Partial update — only supplied fields change."""
    project = get_project(session, project_id)
    if name is not None:
        project.name = name
    if description is not None:
        project.description = description
    project.updated_at = utcnow()
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def delete_project(session: Session, project_id: str) -> dict:
    """DESTRUCTIVE: delete a project and every row it contains.

    Removes the project's characters, assets, scenes (and their shots),
    scripts, style guides, render jobs and those jobs' render outputs —
    database ROWS only; files on disk (asset images, rendered videos) are
    intentionally kept. The ACTIVE project cannot be deleted (422) — switch
    to another project first.
    """
    project = get_project(session, project_id)
    if project.is_active:
        raise ValidationFailedError(
            f"project {project_id} is the active project — activate another "
            "project before deleting it"
        )

    deleted: dict[str, int] = {}

    scenes = session.exec(
        select(Scene).where(col(Scene.project_id) == project_id)
    ).all()
    shot_count = 0
    entity_ids: list[str] = []
    for scene in scenes:
        entity_ids.append(scene.id)
        for shot in session.exec(select(Shot).where(Shot.scene_id == scene.id)).all():
            session.delete(shot)
            entity_ids.append(shot.id)
            shot_count += 1
        session.delete(scene)
    # Revision history belongs to the deleted entities — drop it with them.
    if entity_ids:
        from app.models import Revision

        for rev in session.exec(
            select(Revision).where(col(Revision.entity_id).in_(entity_ids))
        ).all():
            session.delete(rev)
    deleted["scenes"] = len(scenes)
    deleted["shots"] = shot_count

    jobs = session.exec(
        select(RenderJob).where(col(RenderJob.project_id) == project_id)
    ).all()
    output_count = 0
    for job in jobs:
        for output in session.exec(
            select(RenderOutput).where(RenderOutput.render_job_id == job.id)
        ).all():
            session.delete(output)
            output_count += 1
        session.delete(job)
    deleted["render_jobs"] = len(jobs)
    deleted["render_outputs"] = output_count

    for model, key in ((Character, "characters"), (Asset, "assets"),
                       (Script, "scripts"), (StyleGuide, "style_guides")):
        rows = session.exec(
            select(model).where(col(model.project_id) == project_id)  # type: ignore[arg-type]
        ).all()
        for row in rows:
            session.delete(row)
        deleted[key] = len(rows)

    session.delete(project)
    session.commit()
    return deleted


def counts(session: Session, project_id: str) -> dict:
    """Row counts for the UI: scenes/characters/assets/scripts."""
    out: dict[str, int] = {}
    for model, key in ((Scene, "scenes"), (Character, "characters"),
                       (Asset, "assets"), (Script, "scripts")):
        out[key] = session.exec(
            select(func.count())
            .select_from(model)
            .where(col(model.project_id) == project_id)  # type: ignore[arg-type]
        ).one()
    return out


# ---------------------------------------------------------------------------
# Export / import — full project portability as a single zip.
#
# The zip carries:
#   - manifest.json: the project row, every owned row serialised to JSON, and a
#     list of media files that could not be bundled (missing on disk).
#   - media/<relative-path>: the referenced media files, addressed relative to
#     the storage root so import can place them back under a fresh storage root.
#
# Import recreates everything as a NEW (inactive) project, remapping ALL ids so
# imported rows never collide with existing ones; every cross-reference (scene ->
# characters/assets, shot -> scene/assets, output -> job, etc.) is rewritten to
# the new ids, and bundled media is copied under the storage root with new file
# paths. Robust to missing media: export skips with a manifest note; import
# recreates the row without a usable file_path.
# ---------------------------------------------------------------------------
EXPORT_VERSION = 1
_MEDIA_PREFIX = "media"

# (manifest key, model, the id-bearing FK fields that point at other rows). The
# import remapper rewrites each FK using the id map; *_json list fields are
# rewritten element-wise. Order matters: parents before children for clean FK
# resolution, though the remapper handles forward refs via a single id map.
_EXPORT_TABLES: list[tuple[str, type]] = [
    ("characters", Character),
    ("assets", Asset),
    ("scripts", Script),
    ("scenes", Scene),
    ("shots", Shot),
    ("style_guides", StyleGuide),
    ("render_jobs", RenderJob),
    ("render_outputs", RenderOutput),
]

# Media-bearing path fields per model: rewritten on import to the copied file.
_MEDIA_FIELDS: dict[type, tuple[str, ...]] = {
    Asset: ("file_path",),
    RenderOutput: ("video_path", "thumbnail_path", "captioned_path"),
}


def _storage_root() -> Path:
    return Path(get_settings().storage_root)


def _archive_member(file_path: str) -> str | None:
    """Archive member name for a stored media path, relative to the storage root.

    Returns None when the path is outside the storage root (we only bundle files
    we own)."""
    root = _storage_root().resolve()
    p = Path(file_path)
    abs_p = p if p.is_absolute() else (Path.cwd() / p)
    try:
        rel = abs_p.resolve().relative_to(root)
    except ValueError:
        # Stored paths are typically '<storage_root.name>/...'; fall back to the
        # path's tail after the storage-root directory name.
        parts = p.parts
        name = root.name
        if name in parts:
            idx = len(parts) - 1 - parts[::-1].index(name)
            rel = Path(*parts[idx + 1 :])
        else:
            rel = Path(p.name)
    return f"{_MEDIA_PREFIX}/{rel.as_posix()}"


def _ondisk_path(file_path: str) -> Path:
    """Resolve a stored media path to its on-disk absolute location."""
    p = Path(file_path)
    return p if p.is_absolute() else (Path.cwd() / p)


def _project_rows(session: Session, project_id: str) -> dict[str, list]:
    """Every owned row for a project, by manifest key. Shots come via scenes
    (shots have no project_id); render outputs come via render jobs."""
    rows: dict[str, list] = {}
    scene_ids: list[str] = []
    job_ids: list[str] = []
    for key, model in _EXPORT_TABLES:
        if model is Shot:
            items = (
                session.exec(
                    select(Shot).where(col(Shot.scene_id).in_(scene_ids))
                ).all()
                if scene_ids
                else []
            )
        elif model is RenderOutput:
            items = (
                session.exec(
                    select(RenderOutput).where(
                        col(RenderOutput.render_job_id).in_(job_ids)
                    )
                ).all()
                if job_ids
                else []
            )
        else:
            items = session.exec(
                select(model).where(col(model.project_id) == project_id)  # type: ignore[arg-type]
            ).all()
        rows[key] = list(items)
        if model is Scene:
            scene_ids = [s.id for s in items]
        if model is RenderJob:
            job_ids = [j.id for j in items]
    return rows


def export_project(session: Session, project_id: str) -> bytes:
    """Serialise a project (rows + referenced media) into a zip; returns bytes.

    Robust to missing files: a media path that does not exist on disk is skipped
    and recorded under manifest['missing_files']."""
    project = get_project(session, project_id)
    rows = _project_rows(session, project_id)

    manifest: dict = {
        "version": EXPORT_VERSION,
        "project": {"name": project.name, "description": project.description,
                    "id": project.id},
        "rows": {key: [r.model_dump(mode="json") for r in items]
                 for key, items in rows.items()},
        "missing_files": [],
    }

    # Collect media files to bundle (dedup by archive member).
    members: dict[str, Path] = {}
    for key, model in _EXPORT_TABLES:
        fields = _MEDIA_FIELDS.get(model)
        if not fields:
            continue
        for row in rows[key]:
            for field in fields:
                file_path = getattr(row, field, None)
                if not file_path:
                    continue
                member = _archive_member(file_path)
                disk = _ondisk_path(file_path)
                if member is None or not disk.is_file():
                    manifest["missing_files"].append(
                        f"{key}.{row.id}.{field}: {file_path}"
                    )
                    continue
                members[member] = disk

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for member, disk in members.items():
            zf.write(disk, member)
    return buf.getvalue()


# Per-model fields that hold a single foreign id to remap (besides project_id),
# and list fields of ids to remap element-wise.
_FK_FIELDS: dict[type, tuple[str, ...]] = {
    Asset: ("character_id",),
    Scene: ("script_id",),
    Shot: ("scene_id",),
    RenderJob: ("scene_id", "shot_id"),
    RenderOutput: ("render_job_id",),
}
_FK_LIST_FIELDS: dict[type, tuple[str, ...]] = {
    Character: ("reference_asset_ids_json",),
    Scene: ("character_ids_json", "asset_ids_json"),
    Shot: ("asset_ids_json",),
    StyleGuide: ("reference_asset_ids_json",),
}


def _validate_manifest(zf: zipfile.ZipFile) -> dict:
    """Parse and validate an export archive's manifest BEFORE anything is
    created, so a malformed archive fails fast with ValidationFailedError (422)
    and never leaves a partially-built (orphan) project behind.

    Checks: a readable JSON manifest with a dict ``rows`` whose every table is a
    list of dict rows, and every row carries a non-empty ``id``."""
    try:
        manifest = json.loads(zf.read("manifest.json"))
    except (KeyError, json.JSONDecodeError) as exc:
        raise ValidationFailedError(
            "import archive is missing a valid manifest"
        ) from exc

    if not isinstance(manifest, dict):
        raise ValidationFailedError("import manifest is not a valid object")

    rows = manifest.get("rows")
    if not isinstance(rows, dict):
        raise ValidationFailedError("import manifest is missing its 'rows' section")

    for _key, model in _EXPORT_TABLES:
        items = rows.get(_key, [])
        if not isinstance(items, list):
            raise ValidationFailedError(
                f"import manifest table '{_key}' is not a list of rows"
            )
        for raw in items:
            if not isinstance(raw, dict) or not raw.get("id"):
                raise ValidationFailedError(
                    f"import manifest row in '{_key}' is missing an 'id'"
                )
    return manifest


def import_project(session: Session, blob: bytes) -> Project:
    """Recreate a project from an export zip as a NEW (inactive) project.

    All ids are remapped to avoid collisions; cross-references and media paths
    are rewritten. Raises ValidationFailedError (-> 422) on a malformed archive.

    Transactional: the archive is fully validated BEFORE anything is created,
    and the whole build (project + media restore + row recreation) is guarded so
    that ANY failure rolls back and deletes the just-created project — a bad
    import never leaves an orphaned empty project behind."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as exc:
        raise ValidationFailedError("import file is not a valid zip archive") from exc

    # 1) Validate up front — raises ValidationFailedError on malformed input
    #    BEFORE we create any database rows.
    manifest = _validate_manifest(zf)
    rows = manifest["rows"]
    src_meta = manifest.get("project") or {}

    # 2) New project (kept inactive — import must never steal focus).
    project = Project(
        name=f"{src_meta.get('name', 'Imported project')} (imported)",
        description=src_meta.get("description", ""),
        is_active=False,
    )
    session.add(project)
    session.commit()
    session.refresh(project)

    try:
        # 3) Build the id map across every row, up front, so forward references
        #    (e.g. a scene referencing an asset listed later) resolve cleanly.
        id_map: dict[str, str] = {}
        for key, model in _EXPORT_TABLES:
            for raw in rows.get(key, []):
                old = raw["id"]  # validated present above
                if old not in id_map:
                    id_map[old] = new_id(_id_prefix(model))

        # 4) Copy media files out of the zip into the storage root, mapping each
        #    archive member to its new on-disk path (keyed by the OLD path).
        path_map = _restore_media(zf, rows, id_map)

        # 5) Recreate rows with remapped ids/fks/paths.
        for key, model in _EXPORT_TABLES:
            for raw in rows.get(key, []):
                data = dict(raw)
                data["id"] = id_map[raw["id"]]
                if "project_id" in _columns(model):
                    data["project_id"] = project.id
                for field in _FK_FIELDS.get(model, ()):
                    old = data.get(field)
                    if old:
                        data[field] = id_map.get(old, old)
                for field in _FK_LIST_FIELDS.get(model, ()):
                    data[field] = [id_map.get(i, i) for i in (data.get(field) or [])]
                for field in _MEDIA_FIELDS.get(model, ()):
                    old = data.get(field)
                    if old and old in path_map:
                        data[field] = path_map[old]
                    elif old:
                        # Media was missing at export — drop the dangling path.
                        data[field] = None
                session.add(model(**_filter_columns(model, data)))
        session.commit()
    except Exception:
        # Roll back the in-flight inserts, then delete the just-created project
        # so a failed import leaves NO orphan behind.
        session.rollback()
        orphan = session.get(Project, project.id)
        if orphan is not None:
            session.delete(orphan)
            session.commit()
        raise

    session.refresh(project)
    return project


def _restore_media(
    zf: zipfile.ZipFile, rows: dict, id_map: dict[str, str]
) -> dict[str, str]:
    """Copy bundled media into the storage root, returning {old_path -> new_path}.

    Files are placed under <storage_root>/imported/<new_project_member> so an
    import never overwrites existing media; the new path is absolute."""
    root = _storage_root()
    members = set(zf.namelist())
    path_map: dict[str, str] = {}
    for key, model in _EXPORT_TABLES:
        for field in _MEDIA_FIELDS.get(model, ()):
            for raw in rows.get(key, []):
                old = raw.get(field)
                if not old:
                    continue
                member = _archive_member(old)
                if member is None or member not in members:
                    continue
                rel = member[len(_MEDIA_PREFIX) + 1 :]
                dest = root / "imported" / id_map[raw["id"]] / Path(rel).name
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, dest.open("wb") as out:
                    shutil.copyfileobj(src, out)
                path_map[old] = str(dest)
    return path_map


def _id_prefix(model: type) -> str:
    return {
        Character: "char",
        Asset: "asset",
        Script: "script",
        Scene: "scene",
        Shot: "shot",
        StyleGuide: "style",
        RenderJob: "job",
        RenderOutput: "out",
    }[model]


def _columns(model: type) -> set[str]:
    return set(model.model_fields)


def _datetime_fields(model: type) -> set[str]:
    from datetime import datetime as _dt

    out: set[str] = set()
    for name, field in model.model_fields.items():
        ann = field.annotation
        if ann is _dt or _dt in getattr(ann, "__args__", ()):  # handles Optional
            out.add(name)
    return out


def _filter_columns(model: type, data: dict) -> dict:
    """Keep only keys that are real columns of *model* (drop unknown manifest
    keys defensively, e.g. from a newer export version) and parse ISO datetime
    strings back into datetimes (JSON export serialises them to strings)."""
    from datetime import datetime as _dt

    cols = _columns(model)
    dt_fields = _datetime_fields(model)
    out: dict = {}
    for k, v in data.items():
        if k not in cols:
            continue
        if k in dt_fields and isinstance(v, str):
            try:
                v = _dt.fromisoformat(v)
            except ValueError:
                v = utcnow()
        out[k] = v
    return out
