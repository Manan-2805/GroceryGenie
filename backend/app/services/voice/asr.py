import contextlib
import logging
import os
import shutil
import tempfile
import wave
from pathlib import Path
from typing import Any

import onnx_asr

from app.core.config import settings

logger = logging.getLogger("app.services.voice.asr")

MODEL_NAME = "nemo-parakeet-tdt-0.6b-v3"
_asr_model: Any | None = None


def get_asr_model() -> Any:
    global _asr_model
    if _asr_model is None:
        # Cache validation and self-healing
        hf_home = os.environ.get("HF_HOME")
        if hf_home:
            cache_dir = (
                Path(hf_home) / "hub" / "models--istupakov--parakeet-tdt-0.6b-v3-onnx"
            )
            if cache_dir.exists():
                corrupted = False
                for f in cache_dir.rglob("*"):
                    if f.is_file() and f.stat().st_size == 0:
                        corrupted = True
                        break
                if corrupted:
                    logger.warning(
                        f"Corrupted 0-byte files found in ASR cache at {cache_dir}. "
                        "Removing corrupted cache folder to trigger fresh download."
                    )
                    shutil.rmtree(cache_dir, ignore_errors=True)

        logger.info(
            f"Loading Parakeet ASR model using providers {settings.parsed_asr_providers}..."
        )
        try:
            _asr_model = onnx_asr.load_model(
                MODEL_NAME, providers=settings.parsed_asr_providers
            )
            logger.info("Parakeet ASR model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load Parakeet ASR model: {e}")
            raise
    return _asr_model


def transcribe_pcm_chunk(pcm_data: bytes, sample_rate: int = 16000) -> str:
    """Writes raw PCM data to a temporary wav file and recognizes speech.

    Uses NamedTemporaryFile with automatic cleanup instead of manual mkstemp.
    """
    model = get_asr_model()

    # Check if model supports in-memory recognition (buffer interface)
    try:
        # Some ONNX ASR models support direct buffer recognition
        if hasattr(model, "recognize_buffer") and callable(model.recognize_buffer):
            result = model.recognize_buffer(pcm_data, sample_rate)
            return str(result).strip()
    except (AttributeError, RuntimeError):
        logger.debug("ASR buffer recognition not available, using file fallback")

    # Fallback: write to temporary file with auto-cleanup
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            temp_path = tmp.name
            # Write WAV header and PCM data
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
