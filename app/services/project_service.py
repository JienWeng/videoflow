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

from sqlalchemy import update
from sqlmodel import Session, col, func, select

from app.errors import NotFoundError, ValidationFailedError
from app.models import (
    Asset,
    Character,
    Project,
    RenderJob,
    RenderOutput,
    Scene,
    Script,
    Shot,
    StyleGuide,
)
from app.models.base import utcnow

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
    for scene in scenes:
        for shot in session.exec(select(Shot).where(Shot.scene_id == scene.id)).all():
            session.delete(shot)
            shot_count += 1
        session.delete(scene)
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
