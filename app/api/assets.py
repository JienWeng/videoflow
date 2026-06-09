"""Asset endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.services import asset_service

router = APIRouter(prefix="/assets", tags=["assets"])


class RecogniseRequest(BaseModel):
    description: str


@router.post("/upload")
def upload_asset(
    file: UploadFile = File(...),
    asset_type: str | None = Form(None),
    character_id: str | None = Form(None),
    session: Session = Depends(get_session),
):
    asset = asset_service.save_upload(
        session,
        filename=file.filename or "upload",
        fileobj=file.file,
        asset_type=asset_type,
        character_id=character_id,
    )
    return asset


@router.get("")
def list_assets(session: Session = Depends(get_session)):
    return asset_service.list_assets(session)


@router.get("/{asset_id}")
def get_asset(asset_id: str, session: Session = Depends(get_session)):
    return asset_service.get_asset(session, asset_id)


@router.post("/{asset_id}/recognise")
async def recognise(
    asset_id: str, body: RecogniseRequest, session: Session = Depends(get_session)
):
    return await asset_service.recognise(session, asset_id, body.description)
