import asyncio
import contextlib
import json
import logging
import uuid

import numpy as np
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from pipecat.audio.vad.silero import SileroVADAnalyzer
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
VAD_THRESHOLD = 450.0  # RMS amplitude threshold for speech detection
MIN_SILENCE_DURATION = 1.2  # Seconds of silence to trigger end of speech turn
MAX_SPEECH_DURATION = 8.0  # Max speech turn duration in seconds


def calculate_rms(audio_chunk: bytes) -> float:
    """Calculates the RMS amplitude of a PCM 16-bit mono audio chunk."""
    if not audio_chunk:
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
        # Fallback to query param
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
        # Create a new chat session
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

    # Initialize VAD Analyzer
    vad_analyzer = SileroVADAnalyzer(sample_rate=SAMPLE_RATE)
    vad_analyzer.set_sample_rate(SAMPLE_RATE)

    # Initialize State Variables
    audio_buffer = bytearray()
    speech_buffer = bytearray()
    silence_timer = 0.0
    speech_timer = 0.0
    is_speaking = False
    is_playing_response = False

    # Task to stream synthesized voice back to client
    voice_output_queue: asyncio.Queue[bytes] = asyncio.Queue()

    # Send session initialized message
    await websocket.send_json(
        {
            "type": "session_started",
            "session_id": str(session_id),
        }
    )

    async def voice_sender_task() -> None:
        """Reads audio chunks from queue and sends them to the frontend over WebSocket."""
        nonlocal is_playing_response
        try:
            while True:
                chunk = await voice_output_queue.get()
                if chunk == b"EOF":
                    is_playing_response = False
                    await websocket.send_json({"type": "playback_ended"})
                    voice_output_queue.task_done()
                    continue

                # Send binary audio frame
                await websocket.send_bytes(chunk)
                voice_output_queue.task_done()
                await asyncio.sleep(0.01)  # Progressive stream delivery
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in voice sender task: {e}")

    sender_task = asyncio.create_task(voice_sender_task())

    try:
        while True:
            # Receive frame (binary or text)
            frame = await websocket.receive()

            if "bytes" in frame:
                audio_chunk = frame["bytes"]
                audio_buffer.extend(audio_chunk)

                # Process audio chunks in 512-sample (1024-byte) increments for Silero VAD
                while len(audio_buffer) >= 1024:
                    chunk_to_analyze = bytes(audio_buffer[:1024])
                    del audio_buffer[:1024]

                    confidence = vad_analyzer.voice_confidence(chunk_to_analyze)

                    if confidence > 0.5:
                        # User is actively speaking
                        if not is_speaking:
                            is_speaking = True
                            speech_timer = 0.0
                            logger.info("Speech onset detected (Silero VAD).")

                            # Barge-in: User speaks while agent is playing TTS
                            if is_playing_response:
                                logger.info("Barge-in detected! Stopping TTS playback.")
                                while not voice_output_queue.empty():
                                    try:
                                        voice_output_queue.get_nowait()
                                        voice_output_queue.task_done()
                                    except asyncio.QueueEmpty:
                                        break

                                is_playing_response = False
                                await websocket.send_json({"type": "stop_playback"})

                        speech_buffer.extend(chunk_to_analyze)
                        silence_timer = 0.0
                        speech_timer += 512 / SAMPLE_RATE

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
                        silence_timer += 512 / SAMPLE_RATE
                        speech_buffer.extend(chunk_to_analyze)

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

            elif "text" in frame:
                # Handle control messages
                data = json.loads(frame["text"])
                if data.get("type") == "end_session":
                    break
                if data.get("type") == "permission_response":
                    # User approved/denied a cart/checkout action from the voice chat bubble
                    approved = data.get("approved")
                    action = data.get("action")
                    payload = data.get("payload")

                    if approved and action and payload:
                        # Execute the approved mutation
                        res = await orchestrator.execute_approved_mutation(
                            action, payload
                        )
                        # Synthesize response
                        text = res.get("text", "Done.")
                        await websocket.send_json(
                            {
                                "type": "partial_transcript",
                                "text": f"[Action Completed]: {text}",
                            }
                        )
                        is_playing_response = True
                        async for pcm_chunk in synthesize_text_to_pcm_stream(
                            text, emotion="neutral"
                        ):
                            await voice_output_queue.put(pcm_chunk)
                        await voice_output_queue.put(b"EOF")

    except WebSocketDisconnect:
        logger.info("Voice WebSocket disconnected by client.")
    except Exception as e:
        logger.error(f"Error in Voice WebSocket connection: {e}")
    finally:
        # Cancel sender task
        sender_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sender_task

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


async def process_audio_query(
    audio_data: bytes,
    orchestrator: AgentOrchestrator,
    websocket: WebSocket,
    voice_output_queue: asyncio.Queue[bytes],
) -> None:
    """Processes the buffered audio: transcribes it, runs orchestrator, synthesizes TTS and streams output."""
    if len(audio_data) < 16000:  # Skip less than 0.5s audio
        return

    # Send status update
    await websocket.send_json({"type": "status", "status": "transcribing"})

    # 1. Transcribe audio chunk using nemo-parakeet (offload to thread)
    logger.info("Transcribing speech buffer...")
    transcript = await asyncio.to_thread(
        transcribe_pcm_chunk, bytes(audio_data), SAMPLE_RATE
    )
    logger.info(f"ASR Transcript: '{transcript}'")

    if not transcript:
        await websocket.send_json({"type": "status", "status": "idle"})
        return

    # Send final transcription text
    await websocket.send_json({"type": "partial_transcript", "text": transcript})

    # Send orchestrator processing status
    await websocket.send_json({"type": "status", "status": "thinking"})

    # 2. Run agent orchestrator turn
    try:
        result = await orchestrator.run_turn(transcript)

        if result["type"] == "permission_request":
            # Action needs user permission, send JSON control event to frontend
            await websocket.send_json(
                {
                    "type": "permission_request",
                    "action": result["action"],
                    "summary": result["summary"],
                    "payload": result["payload"],
                }
            )
            await websocket.send_json(
                {"type": "status", "status": "waiting_permission"}
            )

            # Synthesize warning voice message progressively
            warning_text = f"I need your permission to {result['summary']}"
            async for pcm_chunk in synthesize_text_to_pcm_stream(
                warning_text, emotion="calm"
            ):
                await voice_output_queue.put(pcm_chunk)
            await voice_output_queue.put(b"EOF")

        else:
            # Standard agent text response
            text_response = result.get("text", "")

            # Emit final text response
            await websocket.send_json(
                {
                    "type": "response",
                    "text": text_response,
                    "navigate_to": result.get("navigate_to"),
                    "navigate_label": result.get("navigate_label"),
                }
            )

            # 3. Synthesize response voice output (TTS) progressively
            emotion = "neutral"
            if any(
                word in text_response.lower()
                for word in ["offer", "deal", "discount", "free", "cheaper"]
            ):
                emotion = "excited"
            elif any(
                word in text_response.lower()
                for word in ["allergy", "warning", "contains", "peanut"]
            ):
                emotion = "calm"

            async for pcm_chunk in synthesize_text_to_pcm_stream(
                text_response, emotion=emotion
            ):
                await voice_output_queue.put(pcm_chunk)
            await voice_output_queue.put(b"EOF")

            await websocket.send_json({"type": "status", "status": "idle"})

    except Exception as e:
        logger.error(f"Error processing agent voice turn: {e}")
        await websocket.send_json(
            {
                "type": "response",
                "text": "Sorry, I had trouble processing your query.",
            }
        )
        await websocket.send_json({"type": "status", "status": "idle"})
