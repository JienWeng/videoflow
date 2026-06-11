"""Background-op status endpoints (long generations triggered with ?background=true)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session
from app.services import op_service

router = APIRouter(tags=["ops"])


@router.get("/ops")
def list_ops(limit: int = 50, session: Session = Depends(get_session)):
    return op_service.list_ops(session, limit=limit)


@router.get("/ops/{op_id}")
def get_op(op_id: str, session: Session = Depends(get_session)):
    return op_service.get_op(session, op_id)
