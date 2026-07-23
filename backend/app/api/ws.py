import asyncio
import contextlib
import json
import logging
import time
import uuid
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from fastapi.websockets import WebSocketState
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.security import decode_access_token
from app.db.models.enums import ChatMode
from app.db.models.session import ChatSession
from app.db.models.user import User
from app.services.agent.orchestrator import AgentOrchestrator
from app.services.voice.asr import transcribe_pcm_chunk
from app.services.voice.tts import synthesize_text_to_pcm_stream

router = APIRouter(prefix="/ws", tags=["Voice WebSocket"])
logger = logging.getLogger("app.api.ws")

# Audio properties
SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2  # 16-bit
VAD_THRESHOLD = 500.0  # RMS amplitude threshold for speech detection (adjusted)
MIN_SILENCE_DURATION = 1.2  # Seconds of silence to trigger end of speech turn
MAX_SPEECH_DURATION = 15.0  # Max speech turn duration in seconds
HEARTBEAT_INTERVAL = 30.0  # Send ping every 30 seconds
HEARTBEAT_TIMEOUT = 30.0  # Close connection if no pong within 30 seconds (increased to accommodate long LLM calls)


async def safe_send_json(websocket: WebSocket, data: dict[str, Any]) -> bool:
    """Safely sends JSON over WebSocket, preventing ASGI exceptions if disconnected."""
    try:
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.send_json(data)
            return True
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as e:
        logger.debug(f"Failed to send JSON over WebSocket: {e}")
    return False


async def safe_send_bytes(websocket: WebSocket, data: bytes) -> bool:
    """Safely sends binary bytes over WebSocket, preventing ASGI exceptions if disconnected."""
    try:
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.send_bytes(data)
            return True
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as e:
        logger.debug(f"Failed to send bytes over WebSocket: {e}")
    return False


def calculate_rms(audio_chunk: bytes) -> float:
    """Calculates the RMS amplitude of a PCM 16-bit mono audio chunk."""
    if not audio_chunk or len(audio_chunk) < 2:
        return 0.0
    audio_data = np.frombuffer(audio_chunk, dtype=np.int16)
    if len(audio_data) == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio_data.astype(np.float64) ** 2)))


@router.websocket("/voice")
async def voice_websocket_endpoint(
    websocket: WebSocket, db: AsyncSession = Depends(get_db)
) -> None:
    await websocket.accept()
    logger.info("Voice WebSocket connection established.")

    # 1. Authenticate user from cookie or query param
    token = websocket.cookies.get("session_token")
    if not token:
        token = websocket.query_params.get("token")

    if not token:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION, reason="Missing token"
        )
        return

    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token"
        )
        return

    # Fetch User
    from sqlalchemy.future import select

    google_sub = payload["sub"]
    user_result = await db.execute(select(User).where(User.google_sub == google_sub))
    user = user_result.scalar_one_or_none()

    if not user:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION, reason="User not found"
        )
        return

    # Extract or create Session ID
    session_id_str = websocket.query_params.get("session_id")
    if session_id_str:
        try:
            session_id = uuid.UUID(session_id_str)
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

    # Initialize State Variables
    audio_buffer = bytearray()
    speech_buffer = bytearray()
    silence_timer = 0.0
    speech_timer = 0.0
    is_speaking = False
    is_playing_response = False
    last_pong_time = asyncio.get_event_loop().time()
    barge_in_cooldown = 0.0  # Prevent echo after barge-in
    vad_chunk_size = 1024  # 512 samples * 2 bytes per sample for VAD processing

    # Voice output queue
    voice_output_queue: asyncio.Queue[bytes] = asyncio.Queue()

    # Send session initialized message
    await safe_send_json(
        websocket,
        {
            "type": "session_started",
            "session_id": str(session_id),
        },
    )

    async def voice_sender_task() -> None:
        """Reads audio chunks from queue and sends them to the frontend over WebSocket."""
        nonlocal is_playing_response
        try:
            while True:
                chunk = await voice_output_queue.get()
                if chunk == b"EOF":
                    is_playing_response = False
                    await safe_send_json(websocket, {"type": "playback_ended"})
                    voice_output_queue.task_done()
                    continue

                # Send binary audio frame
                await safe_send_bytes(websocket, chunk)
                voice_output_queue.task_done()
                await asyncio.sleep(0.01)  # Progressive stream delivery
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in voice sender task: {e}")

    async def heartbeat_task() -> None:
        """Sends periodic pings to keep connection alive and detect disconnection."""
        nonlocal last_pong_time
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                try:
                    sent = await safe_send_json(websocket, {"type": "ping"})
                    if not sent:
                        break
                    # Check if we've received a pong recently
                    elapsed_since_pong = (
                        asyncio.get_event_loop().time() - last_pong_time
                    )
                    if elapsed_since_pong > HEARTBEAT_TIMEOUT:
                        logger.warning("Heartbeat timeout - no pong received")
                        break
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    sender_task = asyncio.create_task(voice_sender_task())
    heartbeat_task_handle = asyncio.create_task(heartbeat_task())

    def stop_tts_playback() -> None:
        """Clears the TTS output queue to stop playback immediately."""
        nonlocal is_playing_response
        while not voice_output_queue.empty():
            try:
                voice_output_queue.get_nowait()
                voice_output_queue.task_done()
            except asyncio.QueueEmpty:
                break
        is_playing_response = False

    try:
        while True:
            # Receive frame (binary or text) with timeout for heartbeat
            frame = await asyncio.wait_for(
                websocket.receive(), timeout=HEARTBEAT_INTERVAL + 5
            )

            if "bytes" in frame:
                audio_chunk = frame["bytes"]
                audio_buffer.extend(audio_chunk)

                # Process audio chunks in 512-sample (1024-byte) increments for VAD
                while len(audio_buffer) >= vad_chunk_size:
                    chunk_to_analyze = bytes(audio_buffer[:vad_chunk_size])
                    del audio_buffer[:vad_chunk_size]

                    # Use RMS-based VAD instead of Silero (avoids sample rate issues)
                    rms = calculate_rms(chunk_to_analyze)
                    is_voice = rms > VAD_THRESHOLD

                    if is_voice:
                        # User is actively speaking
                        if not is_speaking:
                            is_speaking = True
                            speech_timer = 0.0
                            silence_timer = 0.0
                            logger.debug(f"Speech onset detected (RMS={rms:.1f}).")

                        speech_buffer.extend(chunk_to_analyze)
                        silence_timer = 0.0
                        speech_timer += vad_chunk_size / (
                            BYTES_PER_SAMPLE * SAMPLE_RATE
                        )

                        # Barge-in: User speaks for at least 300ms while agent is playing TTS
                        if is_playing_response and speech_timer >= 0.30:
                            logger.info(
                                f"Barge-in confirmed ({speech_timer:.2f}s speech >= 300ms threshold)! Stopping TTS playback."
                            )
                            stop_tts_playback()
                            # Send stop signal and transcribing status to frontend
                            await safe_send_json(websocket, {"type": "stop_playback"})
                            await safe_send_json(
                                websocket, {"type": "status", "status": "transcribing"}
                            )
                            await safe_send_bytes(websocket, b"")
                            barge_in_cooldown = asyncio.get_event_loop().time() + 0.1

                        if speech_timer > MAX_SPEECH_DURATION:
                            logger.info("Max speech duration reached. Processing...")
                            await process_audio_query(
                                bytes(speech_buffer),
                                orchestrator,
                                websocket,
                                voice_output_queue,
                            )
                            speech_buffer.clear()
                            is_speaking = False

                    elif is_speaking:
                        # User was speaking, now silent
                        silence_timer += vad_chunk_size / (
                            BYTES_PER_SAMPLE * SAMPLE_RATE
                        )

                        if silence_timer > MIN_SILENCE_DURATION:
                            logger.info(
                                "Silence duration threshold reached. Speech ended."
                            )
                            is_speaking = False
                            await process_audio_query(
                                bytes(speech_buffer),
                                orchestrator,
                                websocket,
                                voice_output_queue,
                            )
                            speech_buffer.clear()

                # Check barge-in cooldown
                current_time = asyncio.get_event_loop().time()
                if barge_in_cooldown > 0 and current_time < barge_in_cooldown:
                    continue

            elif "text" in frame:
                # Handle control messages
                data = json.loads(frame["text"])
                msg_type = data.get("type", "")

                if msg_type == "end_session":
                    break

                if msg_type == "pong":
                    last_pong_time = asyncio.get_event_loop().time()
                    continue

                if msg_type == "permission_response":
                    approved = data.get("approved")
                    action = data.get("action")
                    payload = data.get("payload")

                    if approved and action and payload:
                        res = await orchestrator.execute_approved_mutation(
                            action, payload
                        )
                        text = res.get("text", "Done.")
                        await safe_send_json(
                            websocket,
                            {
                                "type": "partial_transcript",
                                "text": f"[Action Completed]: {text}",
                            },
                        )
                        is_playing_response = True
                        async for pcm_chunk in synthesize_text_to_pcm_stream(
                            text, emotion="neutral"
                        ):
                            await voice_output_queue.put(pcm_chunk)
                        await voice_output_queue.put(b"EOF")

                # Handle option response from frontend
                if msg_type == "option_response":
                    selected = data.get("selected", "")
                    free_text = data.get("free_text", "")
                    # Create a synthetic user message for the orchestrator
                    synthetic_message = selected
                    if free_text:
                        synthetic_message += f" - {free_text}"

                    # Process through orchestrator
                    is_playing_response = True
                    result = await orchestrator.run_turn(synthetic_message)
                    await handle_orchestrator_result(
                        result, orchestrator, websocket, voice_output_queue
                    )

                # Handle free input
                if msg_type == "free_input":
                    text_input = data.get("text", "")
                    if text_input.strip():
                        is_playing_response = True
                        result = await orchestrator.run_turn(text_input.strip())
                        await handle_orchestrator_result(
                            result, orchestrator, websocket, voice_output_queue
                        )

    except TimeoutError:
        logger.warning("WebSocket receive timeout - closing connection")
    except WebSocketDisconnect:
        logger.info("Voice WebSocket disconnected by client.")
    except Exception as e:
        logger.error(f"Error in Voice WebSocket connection: {e}")
    finally:
        # Cancel tasks
        sender_task.cancel()
        heartbeat_task_handle.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sender_task
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task_handle

        # Clean up database ChatSession ended_at
        try:
            from datetime import datetime

            session_result = await db.execute(
                select(ChatSession).where(ChatSession.id == session_id)
            )
            session_obj = session_result.scalar_one_or_none()
            if session_obj:
                session_obj.ended_at = datetime.utcnow()
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to record session ended time: {e}")

        logger.info("Voice WebSocket connection cleaned up.")


async def handle_orchestrator_result(
    result: dict[str, Any],
    _orchestrator: AgentOrchestrator,
    websocket: WebSocket,
    voice_output_queue: asyncio.Queue[bytes],
) -> None:
    """Handles the orchestrator result, sending appropriate messages and TTS."""
    rtype = str(result["type"])

    if rtype == "permission_request":
        action = str(result.get("action", ""))
        summary = str(result.get("summary", ""))
        payload = result.get("payload", {})
        await safe_send_json(
            websocket,
            {
                "type": "permission_request",
                "action": action,
                "summary": summary,
                "payload": payload,
            },
        )
        await safe_send_json(
            websocket, {"type": "status", "status": "waiting_permission"}
        )

        warning_text = f"I need your permission to {summary}"
        async for pcm_chunk in synthesize_text_to_pcm_stream(
            warning_text, emotion="calm"
        ):
            await voice_output_queue.put(pcm_chunk)
        await voice_output_queue.put(b"EOF")

    elif rtype == "options_response":
        text_val = str(result.get("text", ""))
        options_val = result.get("options", [])
        free_input_val = bool(result.get("free_input_allowed", True))
        await safe_send_json(
            websocket,
            {
                "type": "options_request",
                "text": text_val,
                "options": options_val,
                "free_input_allowed": free_input_val,
            },
        )
        await safe_send_json(
            websocket,
            {
                "type": "tool_result",
                "result": result,
            },
        )
        async for pcm_chunk in synthesize_text_to_pcm_stream(
            text_val, emotion="neutral"
        ):
            await voice_output_queue.put(pcm_chunk)
        await voice_output_queue.put(b"EOF")

    else:
        text_val = str(result.get("text", ""))
        nav_to = result.get("navigate_to")
        nav_label = result.get("navigate_label")
        options_val = result.get("options")
        free_input_val = bool(result.get("free_input_allowed", False))

        await safe_send_json(
            websocket,
            {
                "type": "response",
                "text": text_val,
                "navigate_to": nav_to,
                "navigate_label": nav_label,
                "options": options_val,
                "free_input_allowed": free_input_val,
            },
        )
        await safe_send_json(
            websocket,
            {
                "type": "tool_result",
                "result": result,
            },
        )

        emotion = "neutral"
        if any(
            word in text_val.lower()
            for word in ["offer", "deal", "discount", "free", "cheaper"]
        ):
            emotion = "excited"
        elif any(
            word in text_val.lower()
            for word in ["allergy", "warning", "contains", "peanut"]
        ):
            emotion = "calm"

        async for pcm_chunk in synthesize_text_to_pcm_stream(text_val, emotion=emotion):
            await voice_output_queue.put(pcm_chunk)
        await voice_output_queue.put(b"EOF")

        await safe_send_json(websocket, {"type": "status", "status": "idle"})


async def process_audio_query(
    audio_data: bytes,
    orchestrator: AgentOrchestrator,
    websocket: WebSocket,
    voice_output_queue: asyncio.Queue[bytes],
) -> None:
    """Processes the buffered audio: transcribes it, runs orchestrator, synthesizes TTS."""
    if len(audio_data) < 16000:  # Skip less than 0.5s audio
        return

    # Send status update
    await safe_send_json(websocket, {"type": "status", "status": "transcribing"})

    # 1. Transcribe audio chunk using nemo-parakeet (offload to thread) with timing
    logger.info("Transcribing speech buffer...")
    transcribe_start = time.perf_counter()
    transcript = await asyncio.to_thread(
        transcribe_pcm_chunk, bytes(audio_data), SAMPLE_RATE
    )
    transcribe_duration = time.perf_counter() - transcribe_start
    logger.info(f"ASR Transcript: '{transcript}' (took {transcribe_duration:.3f}s)")

    if not transcript:
        await safe_send_json(websocket, {"type": "status", "status": "idle"})
        return

    # Send final transcription text with timing info
    await safe_send_json(
        websocket,
        {
            "type": "partial_transcript",
            "text": transcript,
            "timing": round(transcribe_duration, 2),
        },
    )

    # Send orchestrator processing status
    await safe_send_json(websocket, {"type": "status", "status": "thinking"})

    # 2. Run agent orchestrator turn
    try:
        turn_start = time.perf_counter()
        result = await orchestrator.run_turn(transcript)
        turn_duration = time.perf_counter() - turn_start
        logger.info(f"Orchestrator turn completed in {turn_duration:.3f}s")

        await handle_orchestrator_result(
            result, orchestrator, websocket, voice_output_queue
        )

    except Exception as e:
        logger.error(f"Error processing agent voice turn: {e}")
        # Fallback: play a random fallback audio instead of showing error
        from app.services.voice.tts import get_random_fallback_audio_pcm

        fallback_pcm = get_random_fallback_audio_pcm()
        if fallback_pcm:
            # Send fallback audio
            chunk_size = 4096
            for i in range(0, len(fallback_pcm), chunk_size):
                chunk = fallback_pcm[i : i + chunk_size]
                await voice_output_queue.put(chunk)
                await asyncio.sleep(0.01)
            await voice_output_queue.put(b"EOF")
            await safe_send_json(
                websocket,
                {
                    "type": "response",
                    "text": "Sorry, I had trouble processing your query.",
                },
            )
        else:
            await safe_send_json(
                websocket,
                {
                    "type": "response",
                    "text": "Sorry, I had trouble processing your query.",
                },
            )
        await safe_send_json(websocket, {"type": "status", "status": "idle"})
