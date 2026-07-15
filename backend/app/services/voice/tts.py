import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any

from piper import PiperVoice
from piper.voice import SynthesisConfig  # type: ignore[attr-defined]

from app.core.config import settings

logger = logging.getLogger("app.services.voice.tts")

# Emotion mapping preset config for Piper voice
EMOTION_PRESETS = {
    "neutral": SynthesisConfig(length_scale=1.0, noise_scale=0.667, noise_w_scale=0.8),
    "excited": SynthesisConfig(length_scale=0.85, noise_scale=0.9, noise_w_scale=1.0),
    "calm": SynthesisConfig(length_scale=1.15, noise_scale=0.5, noise_w_scale=0.6),
    "sad": SynthesisConfig(length_scale=1.3, noise_scale=0.4, noise_w_scale=0.5),
}

_piper_voice: PiperVoice | None = None


def get_piper_voice() -> PiperVoice:
    global _piper_voice
    if _piper_voice is None:
        logger.info(
            f"Loading Piper TTS voice model from {settings.PIPER_VOICE_MODEL}..."
        )
        try:
            _piper_voice = PiperVoice.load(
                settings.PIPER_VOICE_MODEL, config_path=settings.PIPER_VOICE_CONFIG
            )
            logger.info("Piper TTS voice loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load Piper TTS voice: {e}")
            raise
    return _piper_voice


def synthesize_text_to_pcm(text: str, emotion: str = "neutral") -> bytes:
    """Synthesizes text input into raw PCM int16 bytes based on emotion preset."""
    voice = get_piper_voice()
    syn_config = EMOTION_PRESETS.get(emotion, EMOTION_PRESETS["neutral"])

    logger.debug(f"Synthesizing text: '{text}' with emotion preset '{emotion}'")
    chunks = list(voice.synthesize(text, syn_config=syn_config))
    return b"".join(
        c.audio_int16_bytes
        if hasattr(c, "audio_int16_bytes")
        else (c.audio if hasattr(c, "audio") else c)  # type: ignore
        for c in chunks
    )


async def synthesize_text_to_pcm_stream(
    text: str, emotion: str = "neutral"
) -> AsyncGenerator[bytes, None]:
    """Asynchronously synthesizes text and yields raw PCM audio chunks progressively."""
    voice = get_piper_voice()
    syn_config = EMOTION_PRESETS.get(emotion, EMOTION_PRESETS["neutral"])

    logger.debug(
        f"Streaming synthesis of text: '{text}' with emotion preset '{emotion}'"
    )

    iterator = voice.synthesize(text, syn_config=syn_config)

    def next_chunk(it: Any) -> Any:
        try:
            return next(it)
        except StopIteration:
            return None

    while True:
        chunk = await asyncio.to_thread(next_chunk, iterator)
        if chunk is None:
            break

        audio_bytes = (
            chunk.audio_int16_bytes
            if hasattr(chunk, "audio_int16_bytes")
            else (chunk.audio if hasattr(chunk, "audio") else chunk)
        )
        yield audio_bytes
