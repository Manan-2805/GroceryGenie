import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.runner import open_conversation, owned_conversation, run_turn
from app.core.dependencies import get_current_user, get_db
from app.core.security import SESSION_COOKIE
from app.db.base import AsyncSessionFactory
from app.db.models.enums import ChatMode
from app.db.models.session import ChatSession
from app.db.models.user import User

router = APIRouter(prefix="/chat", tags=["Assistant"])


class ChatMessagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(default="", max_length=500)
    session_id: UUID | None = None
    confirmation_id: UUID | None = None
    approved: bool | None = None

    @model_validator(mode="after")
    def check_input(self) -> "ChatMessagePayload":
        if self.confirmation_id is None and (
            not self.message.strip() or self.approved is not None
        ):
            raise ValueError("Send a message or a confirmation decision.")
        if self.confirmation_id is not None and (
            self.session_id is None or self.approved is None
        ):
            raise ValueError("A confirmation requires a conversation and decision.")
        return self


@router.post("/text")
async def text_chat_endpoint(
    request: Request,
    payload: ChatMessagePayload,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    user_id = user.id
    token = request.cookies.get(SESSION_COOKIE)
    session_id = await open_conversation(db, user_id, payload.session_id, ChatMode.text)
    await db.commit()

    async def events() -> AsyncIterator[str]:
        try:
            turn = await run_turn(
                session_id,
                user_id,
                token,
                payload.message.strip()
                or ("Confirm" if payload.approved else "Cancel"),
                payload.confirmation_id,
                payload.approved,
            )
            event = turn.event()
        except HTTPException as exc:
            event = {"type": "response", "text": str(exc.detail)}
        except TimeoutError:
            event = {
                "type": "response",
                "text": "The assistant timed out. Please try again.",
            }
        yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Session-ID": str(session_id),
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/history")
async def chat_history_endpoint(
    session_id: UUID,
    limit: int = Query(default=20, ge=1, le=40),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    chat = await owned_conversation(db, user.id, session_id)
    messages = chat.history[-limit:]
    return {"session_id": str(chat.id), "messages": messages, "count": len(messages)}


@router.get("/conversations")
async def conversations(user: User = Depends(get_current_user)) -> list[dict[str, str]]:
    async with AsyncSessionFactory() as db:
        chats = await db.scalars(
            select(ChatSession)
            .where(ChatSession.user_id == user.id)
            .order_by(ChatSession.updated_at.desc())
            .limit(30)
        )
        return [
            {"id": str(chat.id), "updated_at": chat.updated_at.isoformat()}
            for chat in chats
        ]


@router.delete("/conversations/{session_id}", status_code=204)
async def delete_conversation(
    session_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    chat = await owned_conversation(db, user.id, session_id, lock=True)
    await db.delete(chat)
    await db.commit()
    return Response(status_code=204)
