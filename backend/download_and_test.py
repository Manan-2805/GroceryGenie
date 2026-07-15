import io
import os
from pathlib import Path
import random
import time
import urllib.request
import wave

# Resolve MODELS_DIR: inside Docker, it's mounted at /app/models; otherwise, at backend/models on the host
if Path("/app/models").exists():
    MODELS_DIR = Path("/app/models")
else:
    MODELS_DIR = Path(__file__).resolve().parent / "models"

# Set HF cache home inside the models folder
os.environ["HF_HOME"] = str(MODELS_DIR / "huggingface")

import numpy as np
import onnx_asr
from piper import PiperVoice
from piper.voice import SynthesisConfig

# Optional deps:
#   uv add sounddevice jiwer
try:
    import sounddevice as sd
    MIC_AVAILABLE = True
except (ImportError, OSError):
    MIC_AVAILABLE = False

try:
    from jiwer import wer as jiwer_wer
    JIWER_AVAILABLE = True
except ImportError:
    JIWER_AVAILABLE = False

# ============================================================
# CONFIG
# ============================================================
MODEL_NAME = "nemo-parakeet-tdt-0.6b-v3"

# Add more voices here (accent variety) if you download them.
# Piper voices: https://github.com/rhasspy/piper/blob/master/VOICES.md
PIPER_VOICES = {
    "en_US-lessac-medium": {
        "model": str(MODELS_DIR / "en_US-lessac-medium.onnx"),
        "config": str(MODELS_DIR / "en_US-lessac-medium.onnx.json"),
        "url_model": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
        "url_config": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
    },
    "en_GB-alan-medium": {
        "model": str(MODELS_DIR / "en_GB-alan-medium.onnx"),
        "config": str(MODELS_DIR / "en_GB-alan-medium.onnx.json"),
        "url_model": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/alan/medium/en_GB-alan-medium.onnx",
        "url_config": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json",
    },
}

def ensure_model_files(voice_name: str) -> None:
    voice_info = PIPER_VOICES.get(voice_name)
    if not voice_info:
        return
    
    model_path = Path(voice_info["model"])
    config_path = Path(voice_info["config"])
    
    model_path.parent.mkdir(parents=True, exist_ok=True)
    
    if not model_path.exists():
        print(f"Downloading model for {voice_name} from Hugging Face...")
        urllib.request.urlretrieve(voice_info["url_model"], str(model_path))
        print(f"Saved to {model_path}")
        
    if not config_path.exists():
        print(f"Downloading config for {voice_name} from Hugging Face...")
        urllib.request.urlretrieve(voice_info["url_config"], str(config_path))
        print(f"Saved to {config_path}")

def ensure_embedding_model() -> None:
    embedding_path = MODELS_DIR / "BAAI" / "bge-small-en-v1.5"
    if not (embedding_path.exists() and embedding_path.is_dir()):
        print("Downloading embedding model BAAI/bge-small-en-v1.5 from Hugging Face Hub...")
        try:
            from huggingface_hub import snapshot_download
            snapshot_download(
                repo_id="BAAI/bge-small-en-v1.5",
                local_dir=str(embedding_path),
            )
            print(f"Embedding model downloaded successfully to {embedding_path}")
        except Exception as e:
            print(f"Failed to download embedding model: {e}")

# Piper has no true "emotion" control. This approximates tone by
# varying length_scale (speed) and noise_scale/noise_w (prosody variation).
EMOTION_PRESETS = {
    "neutral": SynthesisConfig(length_scale=1.0, noise_scale=0.667, noise_w_scale=0.8),
    "excited": SynthesisConfig(length_scale=0.85, noise_scale=0.9, noise_w_scale=1.0),
    "calm":    SynthesisConfig(length_scale=1.15, noise_scale=0.5, noise_w_scale=0.6),
    "sad":     SynthesisConfig(length_scale=1.3, noise_scale=0.4, noise_w_scale=0.5),
}

NOISE_TYPES = ["none", "white", "pink", "babble"]
NOISE_SNR_DB = 15  # lower = noisier

CHUNK_SECONDS = 5

AUDIO_DIR = Path("test_audio")
AUDIO_DIR.mkdir(exist_ok=True)

LONG_TEXT_SENTENCES = [
    "Please order 2 kg of tomatoes and 1 liter of milk from the grocery store.",
    "GroceryGenie is an amazing app for smart shopping and inventory management.",
    "Also add a dozen eggs, a loaf of bread, and some fresh spinach to the cart.",
    "Make sure the delivery arrives before six in the evening tomorrow.",
    "If the tomatoes are out of stock, replace them with red bell peppers instead.",
    "Do not forget to apply the weekend discount coupon at checkout.",
]

MIC_TEST_SENTENCES = [
    "Please order 2 kg of tomatoes and 1 liter of milk from the grocery store.",
    "GroceryGenie is an amazing app for smart shopping and inventory management.",
]


# ============================================================
# NOISE GENERATION
# ============================================================
def _rms(x):
    return np.sqrt(np.mean(x.astype(np.float64) ** 2) + 1e-12)


def add_noise(pcm_int16: np.ndarray, noise_type: str, snr_db: float) -> np.ndarray:
    if noise_type == "none":
        return pcm_int16

    signal = pcm_int16.astype(np.float64)
    n = len(signal)

    if noise_type == "white":
        noise = np.random.normal(0, 1, n)
    elif noise_type == "pink":
        white = np.random.normal(0, 1, n)
        fft = np.fft.rfft(white)
        freqs = np.fft.rfftfreq(n)
        freqs[0] = 1e-6
        fft = fft / np.sqrt(freqs)
        noise = np.fft.irfft(fft, n)
    elif noise_type == "babble":
        noise = np.zeros(n)
        for _ in range(6):
            freq = random.uniform(100, 500)
            t = np.arange(n) / 22050.0
            noise += np.sin(2 * np.pi * freq * t) * random.uniform(0.3, 1.0)
        noise += np.random.normal(0, 0.3, n)
    else:
        return pcm_int16

    sig_rms = _rms(signal)
    noise_rms = _rms(noise)
    target_noise_rms = sig_rms / (10 ** (snr_db / 20))
    noise = noise * (target_noise_rms / (noise_rms + 1e-12))

    mixed = signal + noise
    mixed = np.clip(mixed, -32768, 32767)
    return mixed.astype(np.int16)


# ============================================================
# TTS
# ============================================================
def synthesize_to_pcm(voice: PiperVoice, text: str, syn_config: SynthesisConfig) -> np.ndarray:
    chunks = list(voice.synthesize(text, syn_config=syn_config))
    raw_bytes = b''.join(
        c.audio_int16_bytes if hasattr(c, 'audio_int16_bytes')
        else (c.audio if hasattr(c, 'audio') else c)
        for c in chunks
    )
    return np.frombuffer(raw_bytes, dtype=np.int16)


def save_wav(path: Path, pcm_int16: np.ndarray, sample_rate: int):
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(pcm_int16.tobytes())


# ============================================================
# WER / ACCURACY
# ============================================================
def simple_wer(reference: str, hypothesis: str) -> float:
    ref_words = reference.lower().split()
    hyp_words = hypothesis.lower().split()
    d = np.zeros((len(ref_words) + 1, len(hyp_words) + 1), dtype=np.int32)
    for i in range(len(ref_words) + 1):
        d[i][0] = i
    for j in range(len(hyp_words) + 1):
        d[0][j] = j
    for i in range(1, len(ref_words) + 1):
        for j in range(1, len(hyp_words) + 1):
            if ref_words[i - 1] == hyp_words[j - 1]:
                d[i][j] = d[i - 1][j - 1]
            else:
                d[i][j] = 1 + min(d[i - 1][j], d[i][j - 1], d[i - 1][j - 1])
    return d[-1][-1] / max(len(ref_words), 1)


def calc_wer(reference: str, hypothesis: str) -> float:
    if JIWER_AVAILABLE:
        return jiwer_wer(reference, hypothesis)
    return simple_wer(reference, hypothesis)


# ============================================================
# CHUNKED TRANSCRIPTION
# ============================================================
def transcribe_in_chunks(model, pcm_int16: np.ndarray, sample_rate: int, chunk_seconds: int):
    chunk_size = chunk_seconds * sample_rate
    total_chunks = int(np.ceil(len(pcm_int16) / chunk_size))
    full_text_parts = []
    total_time = 0.0

    print(f"\n--- Transcribing in {total_chunks} chunk(s) of ~{chunk_seconds}s ---")
    for idx in range(total_chunks):
        start = idx * chunk_size
        end = min(start + chunk_size, len(pcm_int16))
        chunk_pcm = pcm_int16[start:end]

        tmp_path = AUDIO_DIR / f"_chunk_tmp.wav"
        save_wav(tmp_path, chunk_pcm, sample_rate)

        t0 = time.time()
        result = model.recognize(str(tmp_path))
        dt = time.time() - t0
        total_time += dt

        print(f"[Chunk {idx + 1}/{total_chunks}] ({dt:.3f}s): {result}")
        full_text_parts.append(str(result))

    tmp_path = AUDIO_DIR / "_chunk_tmp.wav"
    if tmp_path.exists():
        tmp_path.unlink()

    return " ".join(full_text_parts).strip(), total_time


# ============================================================
# TEST 1: TTS -> NOISE -> CHUNKED STT -> ACCURACY
# ============================================================
def run_tts_stt_test(model):
    reference_text = " ".join(LONG_TEXT_SENTENCES)

    for voice_name, paths in PIPER_VOICES.items():
        ensure_model_files(voice_name)
        if not Path(paths["model"]).exists():
            print(f"⚠️ Skipping missing voice: {voice_name}")
            continue

        print(f"\n=== Loading voice: {voice_name} ===")
        voice = PiperVoice.load(paths["model"], config_path=paths["config"])
        sample_rate = voice.config.sample_rate

        for emotion_name, syn_config in EMOTION_PRESETS.items():
            print(f"\n>>> Voice: {voice_name} | Emotion/Tone: {emotion_name}")
            pcm = synthesize_to_pcm(voice, reference_text, syn_config)

            for noise_type in NOISE_TYPES:
                print(f"\n--- Noise: {noise_type} (SNR {NOISE_SNR_DB} dB) ---")
                noisy_pcm = add_noise(pcm, noise_type, NOISE_SNR_DB)

                out_path = AUDIO_DIR / f"{voice_name}_{emotion_name}_{noise_type}.wav"
                save_wav(out_path, noisy_pcm, sample_rate)
                print(f"✅ Saved: {out_path}")

                recognized_text, stt_time = transcribe_in_chunks(
                    model, noisy_pcm, sample_rate, CHUNK_SECONDS
                )

                error_rate = calc_wer(reference_text, recognized_text)

                print(f"\nReference : {reference_text}")
                print(f"Recognized: {recognized_text}")
                print(f"WER: {error_rate * 100:.2f}%  |  Total STT time: {stt_time:.3f}s")
                print("=" * 70)


# ============================================================
# TEST 2: LIVE MIC RECORDING -> STT -> ACCURACY
# ============================================================
def record_from_mic(duration_sec: int, sample_rate: int = 16000) -> np.ndarray:
    print(f"🎙️ Recording in 3... 2... 1...")
    time.sleep(1)
    audio = sd.rec(int(duration_sec * sample_rate), samplerate=sample_rate,
                    channels=1, dtype='int16')
    sd.wait()
    print("✅ Recording finished.")
    return audio.flatten()


def run_live_mic_test(model):
    if not MIC_AVAILABLE:
        print("❌ sounddevice not installed. Run: uv add sounddevice")
        return

    sample_rate = 16000
    for i, sentence in enumerate(MIC_TEST_SENTENCES):
        print(f"\n=== Live Mic Test {i + 1} ===")
        print(f"Please read this sentence aloud when recording starts:")
        print(f'  "{sentence}"')
        input("Press Enter to start recording (5 seconds)...")

        pcm = record_from_mic(duration_sec=5, sample_rate=sample_rate)
        out_path = AUDIO_DIR / f"mic_test_{i + 1}.wav"
        save_wav(out_path, pcm, sample_rate)
        print(f"✅ Saved: {out_path}")

        t0 = time.time()
        result = model.recognize(str(out_path))
        stt_time = time.time() - t0

        error_rate = calc_wer(sentence, str(result))

        print(f"\nExpected  : {sentence}")
        print(f"Recognized: {result}")
        print(f"WER: {error_rate * 100:.2f}%  |  STT time: {stt_time:.3f}s")
        print("=" * 70)


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    ensure_embedding_model()
    print("Loading Parakeet with DirectML...")
    stt_model = onnx_asr.load_model(
        MODEL_NAME,
        providers=["DmlExecutionProvider", "CPUExecutionProvider"]
    )
    print("✅ Parakeet loaded\n")

    while True:
        print("\n===== MENU =====")
        print("1. Run TTS -> Noise -> Chunked STT -> Accuracy test")
        print("2. Run Live Mic -> STT -> Accuracy test")
        print("3. Exit")
        choice = input("Select an option: ").strip()

        if choice == "1":
            run_tts_stt_test(stt_model)
        elif choice == "2":
            run_live_mic_test(stt_model)
        elif choice == "3":
            break
        else:
            print("Invalid choice.")