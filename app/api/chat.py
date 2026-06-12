"""Guided-intent chat endpoint. The LLM classifies; the user confirms; the
frontend then calls the real pipeline endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.services import chat_service

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    # Prior turns, oldest first: [{"role": "user"|"assistant", "text": str}].
    # Truncated server-side (last 6 turns, 300 chars each).
    history: list[dict] = []


@router.post("/chat")
async def chat(body: ChatRequest, session: Session = Depends(get_session)):
    return await chat_service.handle_message(
        session, body.message, history=body.history
    )
