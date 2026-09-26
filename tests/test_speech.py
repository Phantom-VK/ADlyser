import wave

import numpy as np
import pytest
import torch

from adlyser.config import VadConfig
from adlyser.errors import PerceptionError
from adlyser.perception.speech import detect_speech, read_wav

VAD = VadConfig(threshold=0.5, min_speech_ms=250, min_silence_ms=100, speech_pad_ms=30)


def write_wav(path, samples, rate=16000, channels=1):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(channels)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(samples.astype(np.int16).tobytes())


def test_read_wav_scales_to_unit_range(tmp_path):
    write_wav(tmp_path / "a.wav", np.array([0, 16384, -32768]))
    audio = read_wav(tmp_path / "a.wav")
    assert audio.dtype == torch.float32
    assert audio.tolist() == pytest.approx([0.0, 0.5, -1.0])


def test_read_wav_rejects_wrong_format(tmp_path):
    write_wav(tmp_path / "a.wav", np.zeros(100), rate=44100)
    with pytest.raises(PerceptionError):
        read_wav(tmp_path / "a.wav")


def test_pure_silence_has_no_speech(tmp_path):
    write_wav(tmp_path / "a.wav", np.zeros(16000 * 3))
    assert detect_speech(tmp_path / "a.wav", VAD) == []
