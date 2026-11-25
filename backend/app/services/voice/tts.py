from functools import lru_cache

from piper import PiperVoice

from app.core.config import settings


@lru_cache(maxsize=1)
def get_piper_voice() -> PiperVoice:
    return PiperVoice.load(settings.piper_model, config_path=settings.piper_config)


def synthesize_text_to_pcm(text: str) -> bytes:
    return b"".join(
        chunk.audio_int16_bytes for chunk in get_piper_voice().synthesize(text)
    )
