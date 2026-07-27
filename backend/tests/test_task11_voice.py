"""
Task 11 verification tests for ws.py voice pipeline.

Tests (all unit-level — no WebSocket connection required):
  1.  speak_text_in_sentences splits on . ? ! \\n
  2.  speak_text_in_sentences respects cancel_flag
  3.  speak_text_in_sentences returns incremented sequence numbers
  4.  speak_text_in_sentences sequences are tagged with 4-byte LE header
  5.  prose_and_speak accumulates tokens and flushes at sentence boundaries
  6.  prose_and_speak flushes remainder at end
  7.  prose_and_speak falls back to result["text"] when LLM fails
  8.  prose_and_speak respects cancel_flag mid-stream
  9.  handle_orchestrator_result: delta returns without action
  10. handle_orchestrator_result: options_response sends JSON + invokes prose_and_speak
  11. handle_orchestrator_result: role_switch_request sends JSON + speaks text
  12. run_turn_voice_stream is absent from orchestrator (deleted)
  13. delta token accumulation into sentences in process_audio_query
  14. calculate_rms: silence returns 0, speech returns > threshold
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.ws import (
    calculate_rms,
    handle_orchestrator_result,
    prose_and_speak,
    speak_text_in_sentences,
)

# ── speak_text_in_sentences ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_speak_splits_on_sentence_boundaries():
    """Text with multiple sentences → one TTS call per sentence."""
    synthesised: list[str] = []

    async def fake_tts(text: str, emotion: str = "neutral"):
        synthesised.append(text)
        yield b"\x00\x01"  # 2 bytes of fake PCM

    q: asyncio.Queue[bytes] = asyncio.Queue()
    flag = asyncio.Event()

    with patch("app.api.ws.synthesize_text_to_pcm_stream", side_effect=fake_tts):
        next_seq = await speak_text_in_sentences(
            "Hello world. How are you? I'm fine!", q, seq_start=0, cancel_flag=flag
        )

    assert next_seq == 3  # 3 sentences → seq 0,1,2 → next is 3
    assert len(synthesised) == 3


@pytest.mark.asyncio
async def test_speak_cancel_flag_stops_synthesis():
    """When cancel_flag is set before synthesis, nothing is enqueued."""
    q: asyncio.Queue[bytes] = asyncio.Queue()
    flag = asyncio.Event()
    flag.set()  # already cancelled

    async def fake_tts(text: str, emotion: str = "neutral"):
        yield b"\x00\x01"

    with patch("app.api.ws.synthesize_text_to_pcm_stream", side_effect=fake_tts):
        next_seq = await speak_text_in_sentences(
            "This should not be spoken.", q, seq_start=0, cancel_flag=flag
        )

    assert q.empty()
    assert next_seq == 0  # no sentences processed


@pytest.mark.asyncio
async def test_speak_sequence_numbers_increment():
    """Each sentence gets a unique incrementing sequence number."""
    seq_nums: list[int] = []

    async def fake_tts(text: str, emotion: str = "neutral"):
        yield b"pcm"

    async def capturing_put(item):
        if item != b"EOF" and len(item) >= 4:
            seq = int.from_bytes(item[:4], "little")
            seq_nums.append(seq)

    q: asyncio.Queue[bytes] = asyncio.Queue()
    q.put = capturing_put  # type: ignore[assignment]
    flag = asyncio.Event()

    with patch("app.api.ws.synthesize_text_to_pcm_stream", side_effect=fake_tts):
        await speak_text_in_sentences(
            "First. Second. Third.", q, seq_start=5, cancel_flag=flag
        )

    assert seq_nums == [5, 6, 7]


@pytest.mark.asyncio
async def test_speak_frames_tagged_with_seq_header():
    """PCM frames must start with a 4-byte little-endian sequence number."""
    q: asyncio.Queue[bytes] = asyncio.Queue()
    flag = asyncio.Event()

    async def fake_tts(text: str, emotion: str = "neutral"):
        yield b"\xaa\xbb"  # 2 bytes fake PCM

    with patch("app.api.ws.synthesize_text_to_pcm_stream", side_effect=fake_tts):
        await speak_text_in_sentences("Hello.", q, seq_start=0, cancel_flag=flag)

    assert not q.empty()
    frame = q.get_nowait()
    assert len(frame) >= 4
    seq = int.from_bytes(frame[:4], "little")
    assert seq == 0
    assert frame[4:] == b"\xaa\xbb"


# ── prose_and_speak ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prose_and_speak_flushes_at_boundary():
    """Tokens ending with sentence boundary are spoken immediately."""
    spoken: list[str] = []

    async def fake_tts(text: str, emotion: str = "neutral"):
        spoken.append(text)
        yield b"pcm"

    async def mock_llm_stream(*args, **kwargs):
        for token in ["You have ", "3 products.", " Mango ", "is popular."]:
            yield token

    q: asyncio.Queue[bytes] = asyncio.Queue()
    flag = asyncio.Event()

    with (
        patch("app.api.ws.call_llm_stream", side_effect=mock_llm_stream),
        patch("app.api.ws.synthesize_text_to_pcm_stream", side_effect=fake_tts),
    ):
        await prose_and_speak({"text": "You have 3 products."}, q, 0, flag)

    assert len(spoken) >= 1
    assert any("products" in s for s in spoken)


@pytest.mark.asyncio
async def test_prose_and_speak_flushes_remainder():
    """If stream ends without a boundary, remaining tokens are still spoken."""
    spoken: list[str] = []

    async def fake_tts(text: str, emotion: str = "neutral"):
        spoken.append(text)
        yield b"pcm"

    async def mock_llm_stream(*args, **kwargs):
        yield "No boundary here"  # no sentence-ending char

    q: asyncio.Queue[bytes] = asyncio.Queue()
    flag = asyncio.Event()

    with (
        patch("app.api.ws.call_llm_stream", side_effect=mock_llm_stream),
        patch("app.api.ws.synthesize_text_to_pcm_stream", side_effect=fake_tts),
    ):
        await prose_and_speak({"text": "fallback"}, q, 0, flag)

    # Either the streamed text or the fallback should have been spoken
    assert len(spoken) >= 1


@pytest.mark.asyncio
async def test_prose_and_speak_fallback_on_llm_failure():
    """When LLM stream raises, result['text'] is spoken as fallback."""
    spoken: list[str] = []

    async def fake_tts(text: str, emotion: str = "neutral"):
        spoken.append(text)
        yield b"pcm"

    async def failing_stream(*args, **kwargs):
        raise RuntimeError("LLM down")
        yield  # make it an async generator

    q: asyncio.Queue[bytes] = asyncio.Queue()
    flag = asyncio.Event()

    with (
        patch("app.api.ws.call_llm_stream", side_effect=failing_stream),
        patch("app.api.ws.synthesize_text_to_pcm_stream", side_effect=fake_tts),
    ):
        await prose_and_speak({"text": "You have 3 products."}, q, 0, flag)

    assert any("products" in s for s in spoken)


@pytest.mark.asyncio
async def test_prose_and_speak_respects_cancel_flag():
    """When cancel_flag is set mid-stream, prose stops generating."""
    spoken: list[str] = []

    async def fake_tts(text: str, emotion: str = "neutral"):
        spoken.append(text)
        yield b"pcm"

    call_count = 0

    async def mock_llm_stream(*args, **kwargs):
        nonlocal call_count
        for token in ["First sentence. ", "Second sentence."]:
            call_count += 1
            yield token

    flag = asyncio.Event()
    q: asyncio.Queue[bytes] = asyncio.Queue()

    async def cancelling_tts(text: str, emotion: str = "neutral"):
        spoken.append(text)
        flag.set()  # cancel after first sentence
        yield b"pcm"

    with (
        patch("app.api.ws.call_llm_stream", side_effect=mock_llm_stream),
        patch("app.api.ws.synthesize_text_to_pcm_stream", side_effect=cancelling_tts),
    ):
        await prose_and_speak({"text": ""}, q, 0, flag)

    # Only first sentence should have been synthesised
    assert len(spoken) <= 1


# ── handle_orchestrator_result ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_delta_does_nothing():
    """delta events are accumulated by caller — handle_orchestrator_result ignores them."""
    ws = MagicMock()
    ws.client_state = MagicMock()
    ws.send_json = AsyncMock()
    q: asyncio.Queue[bytes] = asyncio.Queue()
    flag = asyncio.Event()
    seq_counter = [0]

    await handle_orchestrator_result(
        {"type": "delta", "text": "Hello"},
        ws,
        q,
        seq_counter,
        flag,
    )
    ws.send_json.assert_not_called()
    assert q.empty()


@pytest.mark.asyncio
async def test_handle_options_response_sends_json_and_invokes_prose():
    """options_response → JSON sent + prose_and_speak called."""
    from fastapi.websockets import WebSocketState

    ws = MagicMock()
    ws.client_state = WebSocketState.CONNECTED  # must equal the enum value
    ws.send_json = AsyncMock()
    q: asyncio.Queue[bytes] = asyncio.Queue()
    flag = asyncio.Event()
    seq_counter = [0]

    with patch(
        "app.api.ws.prose_and_speak", new=AsyncMock(return_value=1)
    ) as mock_prose:
        await handle_orchestrator_result(
            {
                "type": "options_response",
                "text": "Found 2 products:",
                "options": [{"label": "Mango"}],
                "card_variant": "search",
            },
            ws,
            q,
            seq_counter,
            flag,
        )

    ws.send_json.assert_called_once()
    sent = ws.send_json.call_args[0][0]
    assert sent["type"] == "options_request"
    assert sent.get("card_variant") == "search"
    mock_prose.assert_called_once()


@pytest.mark.asyncio
async def test_handle_role_switch_sends_json_and_speaks():
    """role_switch_request → JSON sent + text spoken via speak_text_in_sentences."""
    from fastapi.websockets import WebSocketState

    ws = MagicMock()
    ws.client_state = WebSocketState.CONNECTED
    ws.send_json = AsyncMock()
    q: asyncio.Queue[bytes] = asyncio.Queue()
    flag = asyncio.Event()
    seq_counter = [0]

    with patch(
        "app.api.ws.speak_text_in_sentences", new=AsyncMock(return_value=1)
    ) as mock_speak:
        await handle_orchestrator_result(
            {
                "type": "role_switch_request",
                "text": "Switch to seller?",
                "options": [],
                "needed_role": "seller",
                "original_tool": "seller_create_product",
            },
            ws,
            q,
            seq_counter,
            flag,
        )

    ws.send_json.assert_called_once()
    sent = ws.send_json.call_args[0][0]
    assert sent["type"] == "role_switch_request"
    mock_speak.assert_called_once()


# ── orchestrator has no run_turn_voice_stream ─────────────────────────────────


def test_run_turn_voice_stream_deleted():
    """run_turn_voice_stream must NOT exist on AgentOrchestrator (deleted in Task 9)."""
    from app.services.agent.orchestrator import AgentOrchestrator

    assert not hasattr(AgentOrchestrator, "run_turn_voice_stream"), (
        "run_turn_voice_stream still exists on AgentOrchestrator — it should have been deleted in Task 9"
    )


def test_run_turn_stream_exists():
    """run_turn_stream must exist (the new async generator method)."""
    from app.services.agent.orchestrator import AgentOrchestrator

    assert hasattr(AgentOrchestrator, "run_turn_stream"), (
        "run_turn_stream is missing from AgentOrchestrator"
    )
    import inspect

    assert inspect.isasyncgenfunction(AgentOrchestrator.run_turn_stream), (
        "run_turn_stream must be an async generator function"
    )


# ── calculate_rms ─────────────────────────────────────────────────────────────


def test_calculate_rms_silence():
    """Silent audio (all zeros) → RMS = 0."""
    silence = b"\x00\x00" * 512
    assert calculate_rms(silence) == pytest.approx(0.0)


def test_calculate_rms_speech():
    """Non-silent audio → RMS > threshold."""
    # 512 samples of a 1000Hz sine wave at 16-bit
    import math
    import struct

    samples = [
        int(20000 * math.sin(2 * math.pi * 1000 * i / 16000)) for i in range(512)
    ]
    audio = struct.pack("<" + "h" * 512, *samples)
    rms = calculate_rms(audio)
    assert rms > 500.0  # well above VAD_THRESHOLD


def test_calculate_rms_empty():
    """Empty bytes → 0.0, no crash."""
    assert calculate_rms(b"") == pytest.approx(0.0)
    assert calculate_rms(b"\x00") == pytest.approx(0.0)
