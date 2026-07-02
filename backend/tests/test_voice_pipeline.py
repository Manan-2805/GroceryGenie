import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from app.services.voice.asr import transcribe_pcm_chunk
from app.services.voice.tts import synthesize_text_to_pcm


class TestVoicePipeline(unittest.TestCase):
    @patch("app.services.voice.asr.get_asr_model")
    @patch("app.services.voice.asr.tempfile.mkstemp")
    @patch("app.services.voice.asr.wave.open")
    @patch("app.services.voice.asr.os.close")
    @patch("app.services.voice.asr.os.path.exists")
    @patch("app.services.voice.asr.os.remove")
    def test_transcribe_pcm_chunk(
        self,
        mock_remove,
        mock_exists,
        _mock_close,
        mock_wave_open,
        mock_mkstemp,
        mock_get_asr_model,
    ):  # noqa: PLR0913
        mock_exists.return_value = True
        # Mock temp file path
        mock_mkstemp.return_value = (99, "/tmp/mock_chunk.wav")

        # Mock model recognition
        mock_model = MagicMock()
        mock_model.recognize.return_value = "order 2 kg tomatoes"
        mock_get_asr_model.return_value = mock_model

        # Mock wave write context manager
        mock_wave_file = MagicMock()
        mock_wave_open.return_value.__enter__.return_value = mock_wave_file

        # Generate fake PCM bytes (2 seconds of audio)
        sample_rate = 16000
        duration = 2
        t = np.arange(sample_rate * duration) / sample_rate
        fake_pcm = (np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16).tobytes()

        # Run transcription
        result = transcribe_pcm_chunk(fake_pcm, sample_rate)

        # Assertions
        self.assertEqual(result, "order 2 kg tomatoes")
        mock_model.recognize.assert_called_once_with("/tmp/mock_chunk.wav")
        mock_wave_open.assert_called_once_with("/tmp/mock_chunk.wav", "wb")
        mock_wave_file.writeframes.assert_called_once_with(fake_pcm)
        mock_remove.assert_called_once_with("/tmp/mock_chunk.wav")

    @patch("app.services.voice.tts.get_piper_voice")
    def test_synthesize_text_to_pcm(self, mock_get_piper_voice):
        # Mock voice synthesis return chunks
        mock_chunk1 = MagicMock()
        mock_chunk1.audio_int16_bytes = b"\x00\x01\x02\x03"
        mock_chunk2 = MagicMock()
        mock_chunk2.audio_int16_bytes = b"\x04\x05\x06\x07"

        mock_voice = MagicMock()
        mock_voice.synthesize.return_value = [mock_chunk1, mock_chunk2]
        mock_get_piper_voice.return_value = mock_voice

        # Run synthesis
        pcm_bytes = synthesize_text_to_pcm("Hello world", emotion="excited")

        # Assertions
        self.assertEqual(pcm_bytes, b"\x00\x01\x02\x03\x04\x05\x06\x07")
        mock_voice.synthesize.assert_called_once()
        # Verify custom syn_config emotion values are used
        args, kwargs = mock_voice.synthesize.call_args
        self.assertEqual(args[0], "Hello world")
        self.assertAlmostEqual(kwargs["syn_config"].length_scale, 0.85)
