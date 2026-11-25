"""Measure local speech engines with the same short, synthetic English utterances."""

import argparse
import json
import platform
import re
import sys
from pathlib import Path
from statistics import median
from time import perf_counter

import numpy as np
from piper import PiperVoice

from app.services.voice.asr import get_asr_model


def distance(left: list[str], right: list[str]) -> int:
    row = list(range(len(right) + 1))
    for index, first in enumerate(left, 1):
        next_row = [index]
        for position, second in enumerate(right, 1):
            next_row.append(
                min(
                    row[position] + 1,
                    next_row[-1] + 1,
                    row[position - 1] + (first != second),
                )
            )
        row = next_row
    return row[-1]


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("models"))
    parser.add_argument(
        "--candidate", choices=("parakeet", "canary"), default="parakeet"
    )
    args = parser.parse_args()
    prompts = (
        "Find milk under fifty rupees.",
        "Show my orders.",
        "Add two packages of butter to my cart.",
        "Mark this order as packed.",
    )
    start = perf_counter()
    voice = PiperVoice.load(
        args.directory / "en_US-lessac-medium.onnx",
        config_path=args.directory / "en_US-lessac-medium.onnx.json",
    )
    tts_load = perf_counter() - start
    start = perf_counter()
    model_name, folder = (
        ("nemo-parakeet-tdt-0.6b-v2", "asr")
        if args.candidate == "parakeet"
        else ("nemo-conformer-aed", "canary")
    )
    asr = get_asr_model(model_name, args.directory / folder, "int8")
    asr_load = perf_counter() - start
    asr_times, tts_times, results = [], [], []
    for phrase in prompts:
        start = perf_counter()
        pcm = b"".join(chunk.audio_int16_bytes for chunk in voice.synthesize(phrase))
        tts_times.append(perf_counter() - start)
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / np.float32(
            32768.0
        )
        if voice.config.sample_rate != 16000:
            original = np.arange(samples.size)
            resampled = np.arange(0, samples.size, voice.config.sample_rate / 16000)
            samples = np.interp(resampled, original, samples).astype(np.float32)
        started = perf_counter()
        transcript = asr.recognize(samples, sample_rate=16000)
        asr_times.append(perf_counter() - started)
        results.append(
            {
                "reference": phrase,
                "recognized": transcript,
                "word_edits": distance(words(phrase), words(transcript)),
            }
        )
    sys.stdout.write(
        json.dumps(
            {
                "platform": platform.platform(),
                "candidate": args.candidate,
                "sample_type": "Piper-generated speech",
                "tts_load_s": tts_load,
                "asr_load_s": asr_load,
                "tts_p50_s": median(tts_times),
                "asr_p50_s": median(asr_times),
                "asr_per_utterance_s": asr_times,
                "word_error_rate": sum(row["word_edits"] for row in results)
                / sum(len(words(phrase)) for phrase in prompts),
                "transcripts": results,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
