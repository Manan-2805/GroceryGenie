"""
Voice WebSocket endpoint — sentence-level TTS pipeline.

Architecture (per audio turn):
  1. VAD detects speech start/end via RMS threshold
  2. ASR transcribes buffered PCM (offloaded to thread)
  3. orchestrator.run_turn_stream() called with transcript
  4. For each event from run_turn_stream():
     a. If it's a delta token → accumulate into sentence buffer
     b. When sentence boundary hit (. ? ! \\n or 80-token limit) → TTS synthesise
        → send PCM binary frame tagged with sequence number
     c. If it's a structured result (options_response etc.) → send as JSON immediately
        + synthesise result["text"] as prose via VOICE_PROSE_PROMPT LLM call
  5. Frontend plays audio frames in sequence order; second starts when first ends

Barge-in:
  If user speaks ≥300ms while agent is playing TTS:
    - voice_output_queue is drained immediately
    - in-progress prose stream is cancelled via a threading.Event flag
    - frontend receives {"type": "stop_playback"}

All TTS / sequence state is connection-scoped (not in Redis) because it has
no meaning outside this WebSocket connection.

ws.py does NOT call run_turn_voice_stream() — that method was deleted in Task 9.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from fastapi.websockets import WebSocketState
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select as sql_select

from app.core.config import settings
from app.core.dependencies import get_db
from app.core.security import SESSION_COOKIE, authenticated_user
from app.db.models.enums import ChatMode
from app.db.models.session import ChatSession
from app.services.agent.llm import call_llm_stream
from app.services.agent.orchestrator import AgentOrchestrator
from app.services.agent.prompts import VOICE_PROSE_PROMPT
from app.services.voice.asr import transcribe_pcm_chunk
from app.services.voice.tts import (
    get_random_fallback_audio_pcm,
    synthesize_text_to_pcm_stream,
)

router = APIRouter(prefix="/ws", tags=["Voice WebSocket"])
logger = logging.getLogger("app.api.ws")

# ── Audio / VAD constants ─────────────────────────────────────────────────────
SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2  # 16-bit mono
VAD_THRESHOLD = 500.0  # RMS amplitude for speech detection
MIN_SILENCE_DURATION = 1.2  # seconds of silence to end a speech turn
MAX_SPEECH_DURATION = 15.0  # hard cap per utterance
HEARTBEAT_INTERVAL = 30.0
HEARTBEAT_TIMEOUT = 30.0

# ── Sentence buffering constants ──────────────────────────────────────────────
SENTENCE_BOUNDARIES = frozenset({".", "?", "!", "\n"})
SENTENCE_MAX_TOKENS = 80  # flush buffer after this many tokens regardless


# ── WebSocket helpers ─────────────────────────────────────────────────────────


async def safe_send_json(websocket: WebSocket, data: dict[str, Any]) -> bool:
    try:
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.send_json(data)
            return True
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as exc:
        logger.debug(f"safe_send_json failed: {exc}")
    return False


async def safe_send_bytes(websocket: WebSocket, data: bytes) -> bool:
    try:
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.send_bytes(data)
            return True
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as exc:
        logger.debug(f"safe_send_bytes failed: {exc}")
    return False


def calculate_rms(audio_chunk: bytes) -> float:
    if not audio_chunk or len(audio_chunk) < 2:
        return 0.0
    audio_data = np.frombuffer(audio_chunk, dtype=np.int16)
    if len(audio_data) == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio_data.astype(np.float64) ** 2)))


# ── TTS sentence pipeline ─────────────────────────────────────────────────────


async def speak_text_in_sentences(
    text: str,
    voice_output_queue: asyncio.Queue[bytes],
    seq_start: int = 0,
    cancel_flag: asyncio.Event | None = None,
) -> int:
    """Synthesise *text* sentence by sentence and enqueue PCM frames.

    Splits on sentence boundaries (. ? ! \\n). Each sentence is synthesised
    and its PCM bytes sent as a binary WebSocket frame tagged with a sequence
    header (4-byte little-endian sequence number).

    Returns the next sequence number to use.
    """
    # Simple sentence splitter: split on boundary chars, keep them
    sentences: list[str] = []
    current: list[str] = []
    for char in text:
        current.append(char)
        if char in SENTENCE_BOUNDARIES:
            sentence = "".join(current).strip()
            if sentence and sentence not in SENTENCE_BOUNDARIES:
                sentences.append(sentence)
            current = []
    # Flush remainder
    remainder = "".join(current).strip()
    if remainder:
        sentences.append(remainder)

    seq = seq_start
    for sentence in sentences:
        if cancel_flag and cancel_flag.is_set():
            break
        if not sentence.strip():
            continue
        try:
            pcm_chunks: list[bytes] = []
            async for chunk in synthesize_text_to_pcm_stream(
                sentence, emotion="neutral"
            ):
                if cancel_flag and cancel_flag.is_set():
                    break
                pcm_chunks.append(chunk)
            if pcm_chunks and not (cancel_flag and cancel_flag.is_set()):
                pcm_bytes = b"".join(pcm_chunks)
                # Tag with 4-byte little-endian sequence number
                tagged = seq.to_bytes(4, "little") + pcm_bytes
                await voice_output_queue.put(tagged)
                seq += 1
        except Exception as exc:
            logger.warning(f"[TTS] Sentence synthesis failed: {exc}")

    return seq


async def prose_and_speak(
    result: dict[str, Any],
    voice_output_queue: asyncio.Queue[bytes],
    seq_start: int,
    cancel_flag: asyncio.Event,
) -> int:
    """Convert a structured tool result to spoken prose via LLM, then TTS it
    sentence-by-sentence.

    Uses VOICE_PROSE_PROMPT to convert result JSON to 1-3 natural sentences.
    Tokens are accumulated into sentence buffers; each complete sentence is
    synthesised immediately so the user hears the first sentence before the
    LLM has finished generating the full response.

    Returns the next sequence number.
    """
    import json as _json

    result_json = _json.dumps(result, default=str)[:1500]  # cap to avoid huge prompts
    prose_prompt = VOICE_PROSE_PROMPT.format(result_json=result_json)

    token_buffer: list[str] = []
    seq = seq_start

    try:
        async for token in call_llm_stream(
            system_prompt="You convert grocery assistant results to natural speech.",
            user_prompt=prose_prompt,
            temperature=0.3,
            max_tokens=150,
            call_type="voice_prose",
        ):
            if cancel_flag.is_set():
                break
            token_buffer.append(token)

            # Check for sentence boundary in last token
            has_boundary = any(b in token for b in SENTENCE_BOUNDARIES)
            if has_boundary or len(token_buffer) >= SENTENCE_MAX_TOKENS:
                sentence = "".join(token_buffer).strip()
                token_buffer = []
                if sentence:
                    seq = await speak_text_in_sentences(
                        sentence, voice_output_queue, seq, cancel_flag
                    )

        # Flush any remaining tokens
        if token_buffer and not cancel_flag.is_set():
            remainder = "".join(token_buffer).strip()
            if remainder:
                seq = await speak_text_in_sentences(
                    remainder, voice_output_queue, seq, cancel_flag
                )

    except Exception as exc:
        logger.warning(f"[Voice] prose_and_speak LLM stream failed: {exc}")
        # Fallback: speak the result text directly if available
        fallback_text = result.get("text", "")
        if fallback_text and not cancel_flag.is_set():
            seq = await speak_text_in_sentences(
                fallback_text, voice_output_queue, seq, cancel_flag
            )

    return seq


# ── Orchestrator result handler ───────────────────────────────────────────────


async def handle_orchestrator_result(
    result: dict[str, Any],
    websocket: WebSocket,
    voice_output_queue: asyncio.Queue[bytes],
    seq_counter: list[int],  # mutable int wrapper: [current_seq]
    cancel_flag: asyncio.Event,
) -> None:
    """Handle one event from run_turn_stream():

    - delta events: accumulated by the caller (process_audio_query)
    - structured events: sent as JSON + prose → TTS
    """
    rtype = str(result.get("type", "response"))

    if rtype == "delta":
        # Caller handles delta accumulation; nothing to do here
        return

    if rtype == "toggle_theme":
        await safe_send_json(
            websocket, {"type": "toggle_theme", "text": result.get("text", "")}
        )
        return

    if rtype == "role_switch_request":
        await safe_send_json(
            websocket,
            {
                "type": "role_switch_request",
                "text": result.get("text", ""),
                "options": result.get("options", []),
                "needed_role": result.get("needed_role", "seller"),
                "original_tool": result.get("original_tool", ""),
                "free_input_allowed": False,
            },
        )
        # Speak the question
        text_val = str(result.get("text", ""))
        if text_val and not cancel_flag.is_set():
            seq_counter[0] = await speak_text_in_sentences(
                text_val, voice_output_queue, seq_counter[0], cancel_flag
            )
        return

    if rtype == "options_response":
        # Send structured JSON for screen display
        payload: dict[str, Any] = {
            "type": "options_request",
            "text": result.get("text", ""),
            "options": result.get("options", []),
            "free_input_allowed": result.get("free_input_allowed", True),
        }
        if result.get("card_variant"):
            payload["card_variant"] = result["card_variant"]
        await safe_send_json(websocket, payload)

        # Convert to spoken prose for voice users
        if not cancel_flag.is_set():
            seq_counter[0] = await prose_and_speak(
                result, voice_output_queue, seq_counter[0], cancel_flag
            )
        return

    # Default: plain response
    text_val = str(result.get("text", ""))
    if result.get("options"):
        # Has options too — send as options_request
        payload = {
            "type": "options_request",
            "text": text_val,
            "options": result["options"],
            "free_input_allowed": result.get("free_input_allowed", True),
        }
        await safe_send_json(websocket, payload)
    else:
        await safe_send_json(websocket, {"type": "response", "text": text_val})

    if text_val and not cancel_flag.is_set():
        seq_counter[0] = await speak_text_in_sentences(
            text_val, voice_output_queue, seq_counter[0], cancel_flag
        )


# ── Audio query processor ─────────────────────────────────────────────────────


async def process_audio_query(
    audio_data: bytes,
    orchestrator: AgentOrchestrator,
    websocket: WebSocket,
    voice_output_queue: asyncio.Queue[bytes],
    seq_counter: list[int],
    cancel_flag: asyncio.Event,
) -> None:
    """Transcribe audio, run orchestrator, synthesise TTS sentence by sentence."""
    if len(audio_data) < 16000:  # < 0.5s — skip noise bursts
        return

    await safe_send_json(websocket, {"type": "status", "status": "transcribing"})

    transcribe_start = time.perf_counter()
    transcript = await asyncio.to_thread(
        transcribe_pcm_chunk, bytes(audio_data), SAMPLE_RATE
    )
    transcribe_duration = time.perf_counter() - transcribe_start
    logger.info(f"[ASR] '{transcript}' ({transcribe_duration:.3f}s)")

    if not transcript:
        await safe_send_json(websocket, {"type": "status", "status": "idle"})
        return

    await safe_send_json(
        websocket,
        {
            "type": "partial_transcript",
            "text": transcript,
            "timing": round(transcribe_duration, 2),
        },
    )
    await safe_send_json(websocket, {"type": "status", "status": "thinking"})

    cancel_flag.clear()  # fresh turn — reset any previous barge-in

    try:
        turn_start = time.perf_counter()
        delta_buffer: list[str] = []

        async for event in orchestrator.run_turn_stream(transcript):
            if cancel_flag.is_set():
                break

            if event.get("type") == "delta":
                # Accumulate delta tokens into sentence buffers
                token = event.get("text", "")
                delta_buffer.append(token)

                has_boundary = any(b in token for b in SENTENCE_BOUNDARIES)
                if has_boundary or len(delta_buffer) >= SENTENCE_MAX_TOKENS:
                    sentence = "".join(delta_buffer).strip()
                    delta_buffer = []
                    if sentence and not cancel_flag.is_set():
                        seq_counter[0] = await speak_text_in_sentences(
                            sentence, voice_output_queue, seq_counter[0], cancel_flag
                        )
            else:
                # Flush any accumulated delta before handling structured event
                if delta_buffer:
                    sentence = "".join(delta_buffer).strip()
                    delta_buffer = []
                    if sentence and not cancel_flag.is_set():
                        seq_counter[0] = await speak_text_in_sentences(
                            sentence, voice_output_queue, seq_counter[0], cancel_flag
                        )
                await handle_orchestrator_result(
                    event, websocket, voice_output_queue, seq_counter, cancel_flag
                )

        # Flush any remaining delta tokens
        if delta_buffer and not cancel_flag.is_set():
            remainder = "".join(delta_buffer).strip()
            if remainder:
                seq_counter[0] = await speak_text_in_sentences(
                    remainder, voice_output_queue, seq_counter[0], cancel_flag
                )

        # Signal end of this TTS sequence
        await voice_output_queue.put(b"EOF")
        logger.info(
            f"[Voice] Turn completed in {time.perf_counter() - turn_start:.3f}s, seq={seq_counter[0]}"
        )

    except Exception as exc:
        logger.error(f"[Voice] process_audio_query failed: {exc}", exc_info=True)
        fallback_pcm = get_random_fallback_audio_pcm()
        if fallback_pcm:
            chunk_size = 4096
            for i in range(0, len(fallback_pcm), chunk_size):
                await voice_output_queue.put(fallback_pcm[i : i + chunk_size])
        await voice_output_queue.put(b"EOF")
        await safe_send_json(
            websocket,
            {
                "type": "response",
                "text": "Sorry, I had trouble with that. Please try again.",
            },
        )

    await safe_send_json(websocket, {"type": "status", "status": "idle"})


# ── Main WebSocket endpoint ───────────────────────────────────────────────────


@router.websocket("/voice")
async def voice_websocket_endpoint(
    websocket: WebSocket,
    db: AsyncSession = Depends(get_db),
) -> None:
    if websocket.headers.get("origin") not in settings.parsed_origins:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    token = websocket.cookies.get(SESSION_COOKIE)
    user = await authenticated_user(db, token)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    user_id, mode_version = user.id, user.mode_version

    # ── Session ───────────────────────────────────────────────────────────
    session_id_str = websocket.query_params.get("session_id")
    if session_id_str:
        try:
            session_id = uuid.UUID(session_id_str)
            if (
                await db.scalar(
                    sql_select(ChatSession.id).where(
                        ChatSession.id == session_id, ChatSession.user_id == user_id
                    )
                )
                is None
            ):
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
        except ValueError:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION, reason="Invalid Session ID"
            )
            return
    else:
        chat_session = ChatSession(user_id=user.id, mode=ChatMode.voice)
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

    await db.commit()
    await websocket.accept()

    # ── Connection-scoped state ───────────────────────────────────────────
    audio_buffer = bytearray()
    speech_buffer = bytearray()
    silence_timer = 0.0
    speech_timer = 0.0
    is_speaking = False
    is_playing_response = False
    last_pong_time = asyncio.get_event_loop().time()
    vad_chunk_size = 1024

    # Mutable sequence counter (list so nested functions can mutate it)
    seq_counter: list[int] = [0]
    # Cancel flag: set when barge-in detected to abort in-flight TTS
    cancel_flag: asyncio.Event = asyncio.Event()
    voice_output_queue: asyncio.Queue[bytes] = asyncio.Queue()

    await safe_send_json(
        websocket, {"type": "session_started", "session_id": str(session_id)}
    )

    # ── Background tasks ──────────────────────────────────────────────────

    async def voice_sender_task() -> None:
        nonlocal is_playing_response
        try:
            while True:
                frame = await voice_output_queue.get()
                if frame == b"EOF":
                    is_playing_response = False
                    await safe_send_json(websocket, {"type": "playback_ended"})
                    voice_output_queue.task_done()
                    continue
                # First 4 bytes are sequence number (little-endian uint32)
                if len(frame) >= 4:
                    seq_bytes = frame[:4]
                    pcm_bytes = frame[4:]
                    seq_num = int.from_bytes(seq_bytes, "little")
                    # Send sequence metadata as JSON first so frontend can order them
                    await safe_send_json(
                        websocket, {"type": "audio_seq", "seq": seq_num}
                    )
                    await safe_send_bytes(websocket, pcm_bytes)
                else:
                    await safe_send_bytes(websocket, frame)
                voice_output_queue.task_done()
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(f"[Voice sender] error: {exc}")

    async def heartbeat_task() -> None:
        nonlocal last_pong_time
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                sent = await safe_send_json(websocket, {"type": "ping"})
                if not sent:
                    break
                elapsed = asyncio.get_event_loop().time() - last_pong_time
                if elapsed > HEARTBEAT_TIMEOUT:
                    logger.warning("Heartbeat timeout")
                    break
        except asyncio.CancelledError:
            pass

    def drain_audio_queue() -> None:
        """Drain voice_output_queue and set cancel_flag for barge-in."""
        cancel_flag.set()
        while not voice_output_queue.empty():
            try:
                voice_output_queue.get_nowait()
                voice_output_queue.task_done()
            except asyncio.QueueEmpty:
                break

    sender = asyncio.create_task(voice_sender_task())
    heartbeat = asyncio.create_task(heartbeat_task())

    try:
        while True:
            frame = await asyncio.wait_for(
                websocket.receive(), timeout=HEARTBEAT_INTERVAL + 5
            )
            current_user = await authenticated_user(db, token)
            if current_user is None or current_user.mode_version != mode_version:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                break
            await db.commit()

            # ── Binary: PCM audio chunks ──────────────────────────────────
            if "bytes" in frame:
                audio_buffer.extend(frame["bytes"])

                while len(audio_buffer) >= vad_chunk_size:
                    chunk = bytes(audio_buffer[:vad_chunk_size])
                    del audio_buffer[:vad_chunk_size]

                    rms = calculate_rms(chunk)
                    is_voice = rms > VAD_THRESHOLD

                    if is_voice:
                        if not is_speaking:
                            is_speaking = True
                            speech_timer = 0.0
                            silence_timer = 0.0
                        speech_buffer.extend(chunk)
                        silence_timer = 0.0
                        speech_timer += vad_chunk_size / (
                            BYTES_PER_SAMPLE * SAMPLE_RATE
                        )

                        # Barge-in: ≥300ms of speech while agent is playing
                        if is_playing_response and speech_timer >= 0.30:
                            logger.info(
                                f"[Barge-in] {speech_timer:.2f}s speech detected"
                            )
                            drain_audio_queue()
                            await safe_send_json(websocket, {"type": "stop_playback"})
                            await safe_send_json(
                                websocket, {"type": "status", "status": "transcribing"}
                            )

                        if speech_timer > MAX_SPEECH_DURATION:
                            is_speaking = False
                            is_playing_response = True
                            await process_audio_query(
                                bytes(speech_buffer),
                                orchestrator,
                                websocket,
                                voice_output_queue,
                                seq_counter,
                                cancel_flag,
                            )
                            speech_buffer.clear()

                    elif is_speaking:
                        silence_timer += vad_chunk_size / (
                            BYTES_PER_SAMPLE * SAMPLE_RATE
                        )
                        if silence_timer > MIN_SILENCE_DURATION:
                            is_speaking = False
                            is_playing_response = True
                            await process_audio_query(
                                bytes(speech_buffer),
                                orchestrator,
                                websocket,
                                voice_output_queue,
                                seq_counter,
                                cancel_flag,
                            )
                            speech_buffer.clear()

            # ── Text: control messages ────────────────────────────────────
            elif "text" in frame:
                data = json.loads(frame["text"])
                msg_type = data.get("type", "")

                if msg_type == "end_session":
                    break

                if msg_type == "pong":
                    last_pong_time = asyncio.get_event_loop().time()
                    continue

                if msg_type == "permission_response":
                    await safe_send_json(
                        websocket,
                        {
                            "type": "response",
                            "text": "Legacy approvals are unavailable.",
                        },
                    )
                    continue

                if msg_type in ("option_response", "free_input"):
                    text_input = (
                        data.get("selected", "")
                        if msg_type == "option_response"
                        else data.get("text", "")
                    )
                    free_text = (
                        data.get("free_text", "")
                        if msg_type == "option_response"
                        else ""
                    )
                    if free_text:
                        text_input = f"{text_input} - {free_text}"
                    if text_input.strip():
                        is_playing_response = True
                        await process_audio_query(
                            b"",  # no audio — use text input directly
                            orchestrator,
                            websocket,
                            voice_output_queue,
                            seq_counter,
                            cancel_flag,
                        )
                        # Actually run text input path directly
                        cancel_flag.clear()
                        async for event in orchestrator.run_turn_stream(
                            text_input.strip()
                        ):
                            await handle_orchestrator_result(
                                event,
                                websocket,
                                voice_output_queue,
                                seq_counter,
                                cancel_flag,
                            )
                        await voice_output_queue.put(b"EOF")

    except TimeoutError:
        logger.warning("WebSocket receive timeout")
    except WebSocketDisconnect:
        logger.info("Voice WebSocket disconnected by client.")
    except Exception as exc:
        logger.error(f"[Voice WS] Error: {exc}", exc_info=True)
    finally:
        sender.cancel()
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sender
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat

        # Record session end time
        try:
            sess_res = await db.execute(
                sql_select(ChatSession).where(
                    ChatSession.id == session_id, ChatSession.user_id == user_id
                )
            )
            sess_obj = sess_res.scalar_one_or_none()
            if sess_obj:
                sess_obj.ended_at = datetime.utcnow()
                await db.commit()
        except Exception as exc:
            logger.error(f"Failed to record session end: {exc}")

        logger.info("Voice WebSocket cleaned up.")
