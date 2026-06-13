"""Asset endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.schemas.common import ASSET_TYPES
from app.services import asset_service

router = APIRouter(prefix="/assets", tags=["assets"])


class RecogniseRequest(BaseModel):
    description: str


@router.get("/types")
def asset_types():
    """The canonical asset vocabulary — the single source for the upload dropdown
    and the library type filter so they never drift from the AssetType enum."""
    return {"types": list(ASSET_TYPES)}


@router.post("/upload")
def upload_asset(
    file: list[UploadFile] = File(...),
    asset_type: str | None = Form(None),
    character_id: str | None = Form(None),
    session: Session = Depends(get_session),
):
    """Upload one or more files under the form field ``file`` (append it multiple
    times for a multi-file upload). A single asset is returned for one file; a list
    is returned when several files are uploaded at once. Backward compatible with
    callers that send exactly one ``file``."""
    saved_ids = [
        asset_service.save_upload(
            session,
            filename=f.filename or "upload",
            fileobj=f.file,
            asset_type=asset_type,
            character_id=character_id,
        ).id
        for f in file
    ]
    # Re-fetch by id: each save_upload commits, and a commit expires earlier
    # ORM instances, so we read the rows back fresh for serialization.
    saved = [asset_service.get_asset(session, aid) for aid in saved_ids]
    return saved[0] if len(saved) == 1 else saved


@router.get("")
def list_assets(session: Session = Depends(get_session)):
    return asset_service.list_assets(session)


@router.get("/{asset_id}")
def get_asset(asset_id: str, session: Session = Depends(get_session)):
    return asset_service.get_asset(session, asset_id)


@router.delete("/{asset_id}")
def delete_asset(asset_id: str, session: Session = Depends(get_session)):
    detached = asset_service.delete_asset(session, asset_id)
    return {"deleted": asset_id, "detached_from": detached}


@router.post("/{asset_id}/recognise")
async def recognise(
    asset_id: str, body: RecogniseRequest, session: Session = Depends(get_session)
):
    return await asset_service.recognise(session, asset_id, body.description)
