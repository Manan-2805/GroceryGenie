import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from piper import PiperVoice
from piper.voice import SynthesisConfig  # type: ignore[attr-defined]

from app.core.config import MODELS_DIR, settings

logger = logging.getLogger("app.services.voice.tts")

# Emotion mapping preset config for Piper voice
EMOTION_PRESETS = {
    "neutral": SynthesisConfig(length_scale=1.0, noise_scale=0.667, noise_w_scale=0.8),
    "excited": SynthesisConfig(length_scale=0.85, noise_scale=0.9, noise_w_scale=1.0),
    "calm": SynthesisConfig(length_scale=1.15, noise_scale=0.5, noise_w_scale=0.6),
    "sad": SynthesisConfig(length_scale=1.3, noise_scale=0.4, noise_w_scale=0.5),
}

_piper_voice: PiperVoice | None = None

# Fallback audio phrases for TTS error recovery
FALLBACK_PHRASES = [
    "Sorry, something went wrong.",
    "Please try again.",
    "I'm having trouble processing that.",
    "Give me a moment.",
]

# Directory for generated fallback audio files
FALLBACK_AUDIO_DIR = Path(MODELS_DIR) / "fallback_audio"


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


def generate_fallback_audio_files() -> int:
    """Generate fallback audio WAV files from FALLBACK_PHRASES using Piper TTS.
    Files are saved to FALLBACK_AUDIO_DIR with WAV headers.
    Returns the number of files generated (0 if all already exist).
    """
    import wave

    os.makedirs(str(FALLBACK_AUDIO_DIR), exist_ok=True)
    generated_count = 0

    for i, phrase in enumerate(FALLBACK_PHRASES):
        safe_name = f"fallback_{i}.wav"
        filepath = FALLBACK_AUDIO_DIR / safe_name

        if filepath.exists():
            continue

        try:
            pcm_data = synthesize_text_to_pcm(phrase, emotion="neutral")
            with wave.open(str(filepath), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(16000)
                wav_file.writeframes(pcm_data)
            generated_count += 1
            logger.info(f"Generated fallback audio: {filepath} (phrase: '{phrase}')")
        except Exception as e:
            logger.warning(
                f"Failed to generate fallback audio for phrase '{phrase}': {e}"
            )

    return generated_count


def get_random_fallback_audio_pcm() -> bytes:
    """Return the PCM data of a random fallback audio file.
    If no fallback files exist, returns empty bytes.
    """
    import random
    import wave

    if not FALLBACK_AUDIO_DIR.exists():
        return b""

    wav_files = sorted(FALLBACK_AUDIO_DIR.glob("fallback_*.wav"))
    if not wav_files:
        return b""

    chosen = random.choice(wav_files)  # nosec
    try:
        with wave.open(str(chosen), "rb") as wav:
            return wav.readframes(wav.getnframes())
    except Exception as e:
        logger.warning(f"Failed to read fallback audio file {chosen}: {e}")
        return b""
