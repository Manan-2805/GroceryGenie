import asyncio
import json
import logging
from collections.abc import Callable
from time import perf_counter
from uuid import UUID

import numpy as np
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.assistant.runner import open_conversation, run_turn
from app.core.config import settings
from app.core.security import SESSION_COOKIE, authenticated_user
from app.db.base import AsyncSessionFactory
from app.db.models.enums import ChatMode
from app.services.voice.asr import transcribe_pcm_chunk
from app.services.voice.tts import get_piper_voice, synthesize_text_to_pcm

router = APIRouter(prefix="/ws", tags=["Voice"])
logger = logging.getLogger(__name__)

RATE = 16_000
MAX_BYTES = RATE * 2 * 15
SILENCE_BYTES = RATE * 2 * 3 // 5
MIN_VOICED_BYTES = RATE * 2 // 5
PREROLL_BYTES = RATE * 2 * 3 // 20
TRAILING_BYTES = RATE * 2 // 10
MAX_CONNECTIONS = 5
_connections = asyncio.BoundedSemaphore(MAX_CONNECTIONS)
_compute = asyncio.BoundedSemaphore(1)


async def speech_compute[T](fn: Callable[[], T]) -> T:
    async with asyncio.timeout(20):
        await _compute.acquire()
        job = asyncio.create_task(asyncio.to_thread(fn))

        def release(task: asyncio.Task[T]) -> None:
            _compute.release()
            if not task.cancelled():
                task.exception()

        job.add_done_callback(release)
        return await asyncio.shield(job)


class AudioBuffer:
    def __init__(self) -> None:
        self.data = bytearray()
        self.preroll = bytearray()
        self.voiced = 0
        self.silence = 0

    def receive(self, pcm: bytes) -> bytes | None:
        if not 0 < len(pcm) <= 8192 or len(pcm) % 2:
            return None
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
        rms = float(np.sqrt(np.mean(samples**2)))
        if rms >= 450:
            if self.voiced == 0:
                self.data.extend(self.preroll)
                self.preroll.clear()
            self.voiced += len(pcm)
            self.silence = 0
        elif self.voiced:
            self.silence += len(pcm)
        else:
            self.preroll.extend(pcm)
            del self.preroll[:-PREROLL_BYTES]
            return None
        self.data.extend(pcm)
        if self.silence < SILENCE_BYTES and len(self.data) < MAX_BYTES:
            return None
        result = (
            bytes(self.data[: len(self.data) - max(0, self.silence - TRAILING_BYTES)])
            if self.voiced >= MIN_VOICED_BYTES
            else None
        )
        self.data.clear()
        self.voiced = self.silence = 0
        return result


class Control(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    text: str = Field(default="", max_length=500)
    selected: str = Field(default="", max_length=500)
    confirmation_id: UUID | None = None
    approved: bool | None = None


@router.websocket("/voice")
async def voice(websocket: WebSocket) -> None:
    if websocket.headers.get("origin") not in settings.parsed_origins:
        await websocket.close(code=1008)
        return
    token = websocket.cookies.get(SESSION_COOKIE)
    try:
        raw_id = websocket.query_params.get("session_id")
        requested = UUID(raw_id) if raw_id else None
        async with AsyncSessionFactory.begin() as db:
            user = await authenticated_user(db, token)
            if user is None:
                raise HTTPException(401)
            user_id = user.id
            session_id = await open_conversation(db, user_id, requested, ChatMode.voice)
    except (ValueError, HTTPException):
        await websocket.close(code=1008)
        return

    if _connections.locked():
        await websocket.close(code=1013)
        return
    await _connections.acquire()
    active: asyncio.Task[None] | None = None
    audio = AudioBuffer()
    listening = False

    async def speak(message: str) -> None:
        def render() -> tuple[bytes, int]:
            rate = get_piper_voice().config.sample_rate
            return synthesize_text_to_pcm(message[:1400]), rate

        pcm, rate = await speech_compute(render)
        await websocket.send_json({"type": "audio_format", "sample_rate": rate})
        for offset in range(0, len(pcm), 32768):
            await websocket.send_bytes(pcm[offset : offset + 32768])
        await websocket.send_json({"type": "playback_ended"})

    async def turn(
        *,
        pcm: bytes | None = None,
        message: str = "",
        confirmation_id: UUID | None = None,
        approved: bool | None = None,
    ) -> None:
        nonlocal listening
        try:
            if pcm is not None:
                started = perf_counter()
                await websocket.send_json({"type": "status", "status": "transcribing"})
                message = (await speech_compute(lambda: transcribe_pcm_chunk(pcm)))[
                    :500
                ]
                await websocket.send_json(
                    {
                        "type": "partial_transcript",
                        "text": message,
                        "timing": perf_counter() - started,
                    }
                )
                if not message:
                    fallback = "I did not catch that. Try again."
                    await websocket.send_json({"type": "response", "text": fallback})
                    await speak(fallback)
                    return
            await websocket.send_json({"type": "status", "status": "thinking"})
            result = await run_turn(
                session_id, user_id, token, message, confirmation_id, approved
            )
            await websocket.send_json(result.event())
            await speak(result.text)
        except HTTPException as exc:
            await websocket.send_json({"type": "response", "text": str(exc.detail)})
            listening = True
        except (
            TimeoutError,
            OSError,
            ValueError,
            RuntimeError,
            SQLAlchemyError,
        ) as exc:
            logger.warning("voice_turn_failed type=%s", type(exc).__name__)
            await websocket.send_json(
                {
                    "type": "voice_error",
                    "text": "Speech processing is unavailable. You can continue in text mode.",
                }
            )
            await websocket.close(code=1011)

    async def greet() -> None:
        try:
            await speak("Hi! I'm GroceryGenie. How can I help you today?")
        except (TimeoutError, OSError, ValueError, RuntimeError) as exc:
            logger.warning("voice_greeting_failed type=%s", type(exc).__name__)
            await websocket.send_json(
                {
                    "type": "voice_error",
                    "text": "Voice models are unavailable. Use Text Mode.",
                }
            )
            await websocket.close(code=1011)

    try:
        await websocket.accept()
        await websocket.send_json(
            {"type": "session_started", "session_id": str(session_id)}
        )
        active = asyncio.create_task(greet())
        async with asyncio.timeout(1800):
            while True:
                frame = await websocket.receive()
                if frame["type"] == "websocket.disconnect":
                    break
                binary = frame.get("bytes")
                if listening and binary is not None:
                    pcm = audio.receive(binary)
                    if pcm:
                        listening = False
                        active = asyncio.create_task(turn(pcm=pcm))
                raw = frame.get("text")
                if not raw or len(raw) > 4096:
                    continue
                try:
                    control = Control.model_validate(json.loads(raw))
                except (ValueError, ValidationError):
                    continue
                if control.type == "end_session":
                    break
                if control.type == "playback_complete":
                    listening = True
                if control.type == "interrupt":
                    if active and not active.done():
                        active.cancel()
                        await asyncio.gather(active, return_exceptions=True)
                    listening = True
                    audio = AudioBuffer()
                    await websocket.send_json({"type": "stop_playback"})
                if control.type in {
                    "free_input",
                    "option_response",
                    "permission_response",
                } and (active is None or active.done()):
                    message = (control.text or control.selected).strip()
                    if control.type == "permission_response":
                        if control.confirmation_id is None or control.approved is None:
                            continue
                        message = "Confirm" if control.approved else "Cancel"
                    if message:
                        listening = False
                        active = asyncio.create_task(
                            turn(
                                message=message,
                                confirmation_id=control.confirmation_id,
                                approved=control.approved,
                            )
                        )
    except (TimeoutError, WebSocketDisconnect):
        pass
    finally:
        if active is not None:
            active.cancel()
            await asyncio.gather(active, return_exceptions=True)
        _connections.release()
