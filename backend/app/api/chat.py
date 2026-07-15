import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.db.models.enums import ChatMode
from app.db.models.session import ChatSession
from app.db.models.user import User
from app.services.agent.orchestrator import AgentOrchestrator

router = APIRouter(prefix="/chat", tags=["Agent Chat"])
logger = logging.getLogger("app.api.chat")


async def sse_generator(
    orchestrator: AgentOrchestrator,
    user_message: str,
    approved_action: str | None = None,
    approved_payload: dict[str, Any] | None = None,
) -> AsyncGenerator[str, None]:
    try:
        # If this is an approved action execution, run the action
        if approved_action and approved_payload:
            result = await orchestrator.execute_approved_mutation(
                approved_action, approved_payload
            )
        else:
            result = await orchestrator.run_turn(user_message)

        if result["type"] == "permission_request":
            # Emit permission request
            yield f"event: permission_request\ndata: {json.dumps(result)}\n\n"
        else:
            # It's a standard response, simulate token streaming for smooth UI typing effect
            full_text = result.get("text", "")

            # Yield chunks of words
            words = full_text.split(" ")
            for i, word in enumerate(words):
                chunk = word + (" " if i < len(words) - 1 else "")
                data = {"type": "delta", "text": chunk}
                yield f"event: message\ndata: {json.dumps(data)}\n\n"
                await asyncio.sleep(0.04)  # typing effect delay

            # If there's a navigation intent, emit it at the end
            if result.get("navigate_to"):
                nav_data = {
                    "type": "navigate_to",
                    "path": result["navigate_to"],
                    "label": result.get("navigate_label", "Navigating..."),
                }
                yield f"event: navigate_to\ndata: {json.dumps(nav_data)}\n\n"

    except Exception as e:
        logger.error(f"Error in SSE generator: {e}")
        err_data = {
            "type": "error",
            "text": "An error occurred while processing your query.",
        }
        yield f"event: error\ndata: {json.dumps(err_data)}\n\n"


class ChatMessagePayload(BaseModel):
    message: str = Field(..., max_length=200)
    session_id: uuid.UUID | None = None
    approved_action: str | None = None
    approved_payload: dict[str, Any] | None = None


@router.post("/text")
async def text_chat_endpoint(
    payload: ChatMessagePayload,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Text chat endpoint using Server-Sent Events (SSE).
    Accepts user message and optional approval payloads.
    """
    session_id = payload.session_id
    if not session_id:
        # Create a new chat session in Postgres
        chat_session = ChatSession(user_id=user.id, mode=ChatMode.text)
        db.add(chat_session)
        await db.commit()
        await db.refresh(chat_session)
        session_id = chat_session.id

    orchestrator = AgentOrchestrator(
        db=db,
        user_id=user.id,
        session_id=session_id,
        user_role=user.role,
    )

    return StreamingResponse(
        sse_generator(
            orchestrator=orchestrator,
            user_message=payload.message,
            approved_action=payload.approved_action,
            approved_payload=payload.approved_payload,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Session-ID": str(session_id),
        },
    )
