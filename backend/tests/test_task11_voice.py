import asyncio
from threading import Event

import pytest

from app.api.ws import PREROLL_BYTES, TRAILING_BYTES, AudioBuffer, speech_compute


def test_voice_detector_requires_speech_then_silence():
    buffer = AudioBuffer()
    silence = b"\0\0" * 1024
    speech = b"\x00\x03" * 1024
    for _ in range(20):
        assert buffer.receive(silence) is None
    assert not buffer.data

    for _ in range(8):
        assert buffer.receive(speech) is None

    results = [buffer.receive(silence) for _ in range(12)]
    assert [sample for sample in results if sample] == [
        bytes(PREROLL_BYTES) + speech * 8 + bytes(TRAILING_BYTES)
    ]
    assert not buffer.data


def test_voice_detector_bounds_frames_and_utterance():
    buffer = AudioBuffer()
    assert buffer.receive(b"x" * 9000) is None
    assert buffer.receive(b"x") is None
    speech = b"\xff\x03" * 2048
    results = [buffer.receive(speech) for _ in range(125)]
    assert len([sample for sample in results if sample]) == 1
    assert len(buffer.data) < 15 * 32_000


@pytest.mark.asyncio
async def test_cancelled_waiter_retains_compute_capacity_until_engine_stops():
    started = Event()
    release = Event()
    second_started = Event()

    def first_call():
        started.set()
        if not release.wait(5):
            raise TimeoutError

    def second_call():
        second_started.set()
        return 42

    task = asyncio.create_task(speech_compute(first_call))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        next_task = asyncio.create_task(speech_compute(second_call))
        await asyncio.sleep(0)
        assert not second_started.is_set()
    finally:
        release.set()
    assert await next_task == 42
