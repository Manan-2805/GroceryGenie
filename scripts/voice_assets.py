"""Install versioned speech-model files locally. Run with Python 3.12+."""

import argparse
import hashlib
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen

PIPER = "https://huggingface.co/rhasspy/piper-voices/resolve/b145f2ac26522d6a2ccde0164b7b0e48b1e3199c/en/en_US/lessac/medium/"
PARAKEET = "https://huggingface.co/istupakov/parakeet-tdt-0.6b-v2-onnx/resolve/b733f6167f9653fef3cbcffbf101683a5d68b1dd/"
CANARY = "https://huggingface.co/istupakov/canary-180m-flash-onnx/resolve/92c2231/"


def fetch(item: tuple[str, Path]) -> None:
    url, destination = item
    if destination.is_file() and destination.stat().st_size:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = destination.with_suffix(destination.suffix + ".partial")
    with urlopen(url, timeout=90) as response, pending.open("wb") as stream:
        shutil.copyfileobj(response, stream)
    if destination.name == "en_US-lessac-medium.onnx":
        with pending.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != "5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f":
            raise ValueError("Piper ONNX checksum mismatch.")
    pending.replace(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("models"))
    parser.add_argument("--with-parakeet", action="store_true")
    args = parser.parse_args()
    tasks = [
        (PIPER + name, args.directory / name)
        for name in (
            "en_US-lessac-medium.onnx",
            "en_US-lessac-medium.onnx.json",
            "MODEL_CARD",
        )
    ]
    if args.with_parakeet:
        tasks.extend(
            (PARAKEET + name, args.directory / "asr" / name)
            for name in (
                "config.json",
                "vocab.txt",
                "encoder-model.int8.onnx",
                "decoder_joint-model.int8.onnx",
            )
        )
    tasks.extend(
        (CANARY + name, args.directory / "canary" / name)
        for name in (
            "config.json",
            "vocab.txt",
            "encoder-model.int8.onnx",
            "decoder-model.int8.onnx",
        )
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(fetch, tasks))


if __name__ == "__main__":
    main()
