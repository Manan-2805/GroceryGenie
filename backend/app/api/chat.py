"""
Text chat API — Server-Sent Events (SSE).

Streaming contract:
  - delta          → real LLM token stream (out_of_scope, follow_up, free-text)
  - options_request → single complete payload (cart, orders, products, etc.)
  - role_switch_request / toggle_theme / response → single complete payload
  - No fake word-chunking. No asyncio.sleep delays.

BUG-10 fix: card_variant is forwarded in every options_request payload.
"""

import json
import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.db.models.enums import ChatMode
from app.db.models.session import ChatSession
from app.db.models.user import User
from app.services.agent.orchestrator import AgentOrchestrator
from app.services.agent.state_manager import get_history

router = APIRouter(prefix="/chat", tags=["Agent Chat"])
logger = logging.getLogger("app.api.chat")


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _sse(data: dict[str, Any], event: str = "message") -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# SSE generator — consumes run_turn_stream
# ---------------------------------------------------------------------------


async def sse_generator(
    orchestrator: AgentOrchestrator,
    user_message: str,
    approved_action: str | None = None,
    approved_payload: dict[str, Any] | None = None,
) -> AsyncGenerator[str, None]:
    """Consume orchestrator.run_turn_stream() and emit SSE events.

    For approved mutations (legacy permission flow), run execute_approved_mutation
    and emit the result as a single payload.

    For normal turns, iterate run_turn_stream():
      - {"type": "delta", "text": token}   → emit as delta (real LLM stream)
      - any other type                      → emit as single structured payload
    """
    try:
        # Emit thinking status immediately so the UI shows a spinner
        yield _sse({"type": "status", "status": "🧠 Thinking..."})

        # ── Approved mutation (legacy permission_request flow) ─────────────
        if approved_action and approved_payload:
            result = await orchestrator.execute_approved_mutation(
                approved_action, approved_payload
            )
            yield _sse(_build_sse_payload(result))
            return

        # ── Normal turn — consume the async generator ──────────────────────
        async for event in orchestrator.run_turn_stream(user_message):
            yield _sse(_build_sse_payload(event))

    except Exception as exc:
        logger.error(f"[chat.py] SSE generator error: {exc}", exc_info=True)
        yield _sse(
            {"type": "error", "text": "An error occurred. Please try again."},
            event="error",
        )


def _build_sse_payload(result: dict[str, Any]) -> dict[str, Any]:
    """Convert an orchestrator result dict into the SSE wire format.

    Key behaviours:
      - options_response → options_request with card_variant forwarded (BUG-10 fix)
      - delta            → forwarded as-is (real LLM token)
      - toggle_theme, role_switch_request, response → forwarded as-is
    """
    rtype = result.get("type", "response")

    if rtype == "options_response":
        payload: dict[str, Any] = {
            "type": "options_request",
            "text": result.get("text", ""),
            "options": result.get("options", []),
            "free_input_allowed": result.get("free_input_allowed", True),
        }
        # BUG-10 fix: always forward card_variant when present
        if result.get("card_variant"):
            payload["card_variant"] = result["card_variant"]
        return payload

    if rtype == "role_switch_request":
        return {
            "type": "role_switch_request",
            "text": result.get("text", ""),
            "summary": result.get("summary", ""),
            "options": result.get("options", []),
            "needed_role": result.get("needed_role", "seller"),
            "original_tool": result.get("original_tool", ""),
            "free_input_allowed": False,
        }

    if rtype == "toggle_theme":
        return {"type": "toggle_theme", "text": result.get("text", "Theme toggled.")}

    if rtype == "delta":
        # Real LLM token — forward directly, no transformation
        return {"type": "delta", "text": result.get("text", "")}

    if rtype == "navigate_to":
        return {
            "type": "navigate_to",
            "path": result.get("path", ""),
            "label": result.get("label", "Navigating..."),
        }

    # Default: plain response
    payload = {
        "type": "response",
        "text": result.get("text", ""),
    }
    if result.get("options") is not None:
        payload["options"] = result["options"]
    if result.get("free_input_allowed") is not None:
        payload["free_input_allowed"] = result["free_input_allowed"]
    return payload


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ChatMessagePayload(BaseModel):
    message: str = Field(..., max_length=500)
    session_id: uuid.UUID | None = None
    approved_action: str | None = None
    approved_payload: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# POST /chat/text
# ---------------------------------------------------------------------------


@router.post("/text")
async def text_chat_endpoint(
    payload: ChatMessagePayload,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Text chat endpoint using Server-Sent Events (SSE).

    Free-text responses (follow_up, out_of_scope) stream tokens in real time.
    Structured results (cart, orders, products) are sent as a single payload.
    No artificial delays or fake chunking.
    """
    session_id = payload.session_id
    if not session_id:
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


# ---------------------------------------------------------------------------
# GET /chat/history
# ---------------------------------------------------------------------------


@router.get("/history")
async def chat_history_endpoint(
    session_id: uuid.UUID = Query(..., description="Session ID to load history for"),
    limit: int = Query(default=20, ge=1, le=100, description="Max messages to return"),
    user: User = Depends(get_current_user),
    _db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the last N messages for a session.

    Used by the frontend to reload conversation history on page refresh.
    Returns an empty list if the session has expired or never existed.
    """
    messages = await get_history(str(session_id), limit=limit)
    return {
        "session_id": str(session_id),
        "messages": messages,
        "count": len(messages),
    }
