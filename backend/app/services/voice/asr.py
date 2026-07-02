import contextlib
import logging
import os
import tempfile
import wave
from typing import Any

import onnx_asr

from app.core.config import settings

logger = logging.getLogger("app.services.voice.asr")

MODEL_NAME = "nemo-parakeet-tdt-0.6b-v3"
_asr_model: Any | None = None


def get_asr_model() -> Any:
    global _asr_model
    if _asr_model is None:
        logger.info(f"Loading Parakeet ASR model using providers {settings.parsed_asr_providers}...")
        try:
            _asr_model = onnx_asr.load_model(
                MODEL_NAME,
                providers=settings.parsed_asr_providers
            )
            logger.info("Parakeet ASR model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load Parakeet ASR model: {e}")
            raise
    return _asr_model


def transcribe_pcm_chunk(pcm_data: bytes, sample_rate: int = 16000) -> str:
    """Writes raw PCM data to a temporary wav file and recognizes speech."""
    model = get_asr_model()
    
    # Create temp wav file
    fd, temp_path = tempfile.mkstemp(suffix=".wav")
    try:
        os.close(fd)
        with wave.open(temp_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)  # 16-bit
            w.setframerate(sample_rate)
            w.writeframes(pcm_data)
            
        result = model.recognize(temp_path)
        return str(result).strip()
    except Exception as e:
        logger.error(f"ASR transcription failed: {e}")
        return ""
    finally:
        if os.path.exists(temp_path):
            with contextlib.suppress(OSError):
                os.remove(temp_path)



