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
        # Create a shared progress asyncio.Queue and set it on orchestrator
        progress_queue: asyncio.Queue[str] = asyncio.Queue()
        orchestrator._progress_queue = progress_queue

        # Emit initial status
        status_data = {"type": "status", "status": "🧠 Thinking..."}
        yield f"event: message\ndata: {json.dumps(status_data)}\n\n"

        # If this is an approved action execution, run the action
        if approved_action and approved_payload:
            result = await orchestrator.execute_approved_mutation(
                approved_action, approved_payload
            )
        else:
            # Run orchestrator with concurrent progress reading
            result_task = asyncio.create_task(orchestrator.run_turn(user_message))

            # Read progress events while orchestrator runs
            while not result_task.done():
                try:
                    status_text = await asyncio.wait_for(
                        progress_queue.get(), timeout=0.5
                    )
                    status_data = {"type": "status", "status": status_text}
                    yield f"event: message\ndata: {json.dumps(status_data)}\n\n"
                except TimeoutError:
                    pass

            result = result_task.result()

        if result["type"] == "permission_request":
            # Emit permission request
            yield f"event: permission_request\ndata: {json.dumps(result)}\n\n"
        elif result["type"] == "role_switch_request":
            # Emit role switch request as an options_request with special type
            role_switch_data = {
                "type": "role_switch_request",
                "text": result.get("text", ""),
                "summary": result.get("summary", ""),
                "options": result.get("options", []),
                "needed_role": result.get("needed_role", "seller"),
                "original_tool": result.get("original_tool", ""),
                "free_input_allowed": False,
            }
            yield f"event: message\ndata: {json.dumps(role_switch_data)}\n\n"
        elif result.get("type") == "options_response":
            # Emit options request
            options_data = {
                "type": "options_request",
                "text": result.get("text", ""),
                "options": result.get("options", []),
                "free_input_allowed": result.get("free_input_allowed", True),
            }
            yield f"event: message\ndata: {json.dumps(options_data)}\n\n"
        else:
            # It's a standard response - stream tokens in real time
            full_text = result.get("text", "")

            # For simple/short responses (like "Product added to cart"), yield all at once
            # For longer responses, stream via LLM for real-time effect
            if len(full_text) < 100 or result.get("options"):
                # Short response or has options: yield all at once
                data = {"type": "delta", "text": full_text}
                yield f"event: message\ndata: {json.dumps(data)}\n\n"
            else:
                # Stream the response text in chunks for real-time UX
                # Split into reasonable chunks (words or small groups)
                words = full_text.split(" ")
                chunk_size = max(1, len(words) // 20)  # ~20 chunks total
                for i in range(0, len(words), chunk_size):
                    chunk = " ".join(words[i : i + chunk_size])
                    if i + chunk_size < len(words):
                        chunk += " "
                    data = {"type": "delta", "text": chunk}
                    yield f"event: message\ndata: {json.dumps(data)}\n\n"
                    await asyncio.sleep(0.02)  # minimal delay for smooth rendering

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
