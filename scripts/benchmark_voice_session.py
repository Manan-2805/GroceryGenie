"""Measure real local authenticated voice sessions with synthetic audio and no cloud calls."""

import argparse
import asyncio
import json
import os
import sys
from statistics import median
from time import perf_counter
from urllib.parse import urlsplit
from uuid import uuid4

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from websockets.asyncio.client import connect

from app.core.security import SESSION_COOKIE, create_login_session
from app.db.models.user import User
from app.services.voice.tts import get_piper_voice


async def session_keys(count: int) -> list[str]:
    url = os.environ["TEST_DATABASE_URL"]
    if "test" not in url.rsplit("/", 1)[-1].lower():
        raise ValueError("Use a disposable test database for voice fixtures.")
    engine = create_async_engine(url)
    try:
        async with AsyncSession(engine) as db, db.begin():
            keys = []
            for _ in range(count):
                subject = uuid4()
                user = User(
                    google_sub=f"voice-benchmark:{subject}",
                    email=f"{subject}@example.invalid",
                    name="Voice fixture",
                )
                db.add(user)
                await db.flush()
                keys.append(create_login_session(db, user))
            return keys
    finally:
        await engine.dispose()


def phrase_pcm() -> bytes:
    voice = get_piper_voice()
    raw = b"".join(
        chunk.audio_int16_bytes for chunk in voice.synthesize("Show my orders.")
    )
    samples = np.frombuffer(raw, dtype="<i2")
    resampled = np.arange(0, samples.size, voice.config.sample_rate / 16000)
    return (
        np.interp(resampled, np.arange(samples.size), samples).astype("<i2").tobytes()
    )


async def exercise(
    url: str, origin: str, key: str, pcm: bytes
) -> dict[str, float | str]:
    async with connect(
        url, origin=origin, additional_headers={"Cookie": f"{SESSION_COOKIE}={key}"}
    ) as socket:
        async with asyncio.timeout(90):
            greeting_at = perf_counter()
            while True:
                frame = await socket.recv()
                if (
                    isinstance(frame, str)
                    and json.loads(frame)["type"] == "playback_ended"
                ):
                    break
            greeting_s = perf_counter() - greeting_at
            await socket.send(json.dumps({"type": "playback_complete"}))
            for _ in range(4):
                await socket.send(bytes(1024))
                await asyncio.sleep(1024 / 32000)
            for offset in range(0, len(pcm), 1024):
                await socket.send(pcm[offset : offset + 1024])
                await asyncio.sleep(1024 / 32000)
            ended = perf_counter()
            for _ in range(20):
                await socket.send(bytes(1024))
                await asyncio.sleep(1024 / 32000)
            transcript, response, asr_s = "", "", 0.0
            while True:
                frame = await socket.recv()
                if isinstance(frame, bytes):
                    return {
                        "verified": bool(transcript and "No orders" in response),
                        "greeting_s": greeting_s,
                        "end_of_speech_to_first_pcm_s": perf_counter() - ended,
                        "asr_s": asr_s,
                        "transcript": transcript,
                        "reply": response,
                    }
                event = json.loads(frame)
                if event["type"] == "partial_transcript":
                    transcript, asr_s = event["text"], event["timing"]
                if event["type"] == "response":
                    response = event["text"]
                if event["type"] == "voice_error":
                    raise RuntimeError(event["text"])


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8000/api/v1/ws/voice")
    parser.add_argument("--origin", default="http://localhost:5173")
    parser.add_argument("--sessions", type=int, choices=range(1, 6), default=5)
    args = parser.parse_args()
    if urlsplit(args.url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("Run against a loopback GroceryGenie server.")
    keys = await session_keys(args.sessions)
    pcm = phrase_pcm()
    results = await asyncio.gather(
        *(exercise(args.url, args.origin, key, pcm) for key in keys)
    )
    failures = sum(not bool(row["verified"]) for row in results)
    sys.stdout.write(
        json.dumps(
            {
                "sessions": args.sessions,
                "failures": failures,
                "sample_type": "Piper-generated speech",
                "first_pcm_p50_s": median(
                    float(row["end_of_speech_to_first_pcm_s"]) for row in results
                ),
                "results": results,
            },
            indent=2,
        )
        + "\n"
    )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
