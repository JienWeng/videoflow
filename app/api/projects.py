"""Project endpoints — the only place project ids appear in the API.

Everything else scopes implicitly to the server-side ACTIVE project.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.services import project_service

router = APIRouter(prefix="/projects", tags=["projects"])


class CreateProject(BaseModel):
    name: str
    description: str = ""


class ProjectEdit(BaseModel):
    """Partial project update — only supplied fields change."""

    name: str | None = None
    description: str | None = None


def _project_dict(session: Session, project) -> dict:
    return {
        **project.model_dump(),
        "counts": project_service.counts(session, project.id),
    }


@router.get("")
def list_projects(session: Session = Depends(get_session)):
    return [_project_dict(session, p) for p in project_service.list_projects(session)]


@router.get("/active")
def get_active(session: Session = Depends(get_session)):
    return _project_dict(session, project_service.get_active(session))


@router.post("")
def create_project(body: CreateProject, session: Session = Depends(get_session)):
    """Create a project AND make it active — creating a project means
    switching into it."""
    project = project_service.create_project(
        session, name=body.name, description=body.description
    )
    project = project_service.activate(session, project.id)
    return _project_dict(session, project)


@router.post("/{project_id}/activate")
def activate_project(project_id: str, session: Session = Depends(get_session)):
    return _project_dict(session, project_service.activate(session, project_id))


@router.patch("/{project_id}")
def edit_project(
    project_id: str, body: ProjectEdit, session: Session = Depends(get_session)
):
    project = project_service.update_project(
        session, project_id, name=body.name, description=body.description
    )
    return _project_dict(session, project)


@router.delete("/{project_id}")
def delete_project(project_id: str, session: Session = Depends(get_session)):
    """DESTRUCTIVE: deletes the project and its rows (files kept).
    422 when the project is active."""
    deleted = project_service.delete_project(session, project_id)
    return {"deleted": project_id, "rows": deleted}
