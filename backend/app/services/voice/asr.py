from functools import lru_cache
from pathlib import Path

import numpy as np
from onnx_asr.adapters import TextResultsAsrAdapter
from onnx_asr.loader import Manager
from onnxruntime import SessionOptions

from app.core.config import settings


@lru_cache(maxsize=2)
def get_asr_model(
    model: str, directory: Path, quantization: str
) -> TextResultsAsrAdapter:
    if not directory.is_dir():
        raise FileNotFoundError("Local ASR model files are missing.")
    options = SessionOptions()
    options.intra_op_num_threads = 4
    return Manager(sess_options=options, providers=["CPUExecutionProvider"]).create_asr(
        model, directory, quantization=quantization or None, offline=True
    )


def transcribe_pcm_chunk(pcm_data: bytes) -> str:
    if not pcm_data:
        return ""
    model = get_asr_model(
        settings.ASR_MODEL,
        settings.MODELS_DIR / settings.ASR_SUBDIR,
        settings.ASR_QUANTIZATION,
    )
    samples = np.frombuffer(pcm_data, dtype="<i2").astype(np.float32) / np.float32(
        32768.0
    )
    return model.recognize(samples, sample_rate=16000).strip()
