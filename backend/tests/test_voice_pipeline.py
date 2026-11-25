from unittest.mock import MagicMock, patch

import numpy as np

from app.services.voice.asr import transcribe_pcm_chunk
from app.services.voice.tts import synthesize_text_to_pcm


def test_asr_receives_normalized_pcm_without_temp_files():
    with patch("app.services.voice.asr.get_asr_model") as model:
        model.return_value.recognize.return_value = " two packages "
        assert transcribe_pcm_chunk(b"\x00\x80\xff\x7f") == "two packages"
        args, kwargs = model.return_value.recognize.call_args
        np.testing.assert_allclose(args[0], [-1, 32767 / 32768])
        assert kwargs == {"sample_rate": 16000}


def test_asr_skips_empty_pcm_before_loading_model():
    with patch("app.services.voice.asr.get_asr_model") as model:
        assert transcribe_pcm_chunk(b"") == ""
        model.assert_not_called()


def test_piper_preserves_its_pcm_output():
    with patch("app.services.voice.tts.get_piper_voice") as voice:
        voice.return_value.synthesize.return_value = [
            MagicMock(audio_int16_bytes=b"\x01\x00"),
            MagicMock(audio_int16_bytes=b"\x02\x00"),
        ]
        assert synthesize_text_to_pcm("milk") == b"\x01\x00\x02\x00"
        voice.return_value.synthesize.assert_called_once_with("milk")
