"""Speech / silence map from Silero VAD."""

import wave
from pathlib import Path

import numpy as np
import torch
from silero_vad import get_speech_timestamps, load_silero_vad

from adlyser.config import VadConfig
from adlyser.errors import PerceptionError
from adlyser.schemas import SpeechSeg

SAMPLE_RATE = 16000


def read_wav(wav: Path) -> torch.Tensor:
    """Load a 16 kHz mono 16-bit PCM wav as a float32 tensor in [-1, 1].

    :param wav: audio file written by ``extract_wav``.
    :return: 1-D float32 tensor.
    :raises PerceptionError: if the file is not 16 kHz mono 16-bit PCM.
    """
    with wave.open(str(wav), "rb") as f:
        if (f.getframerate(), f.getnchannels(), f.getsampwidth()) != (SAMPLE_RATE, 1, 2):
            raise PerceptionError(f"{wav.name} is not 16 kHz mono 16-bit PCM")
        pcm = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
    return torch.from_numpy(pcm.astype(np.float32) / 32768.0)


def detect_speech(wav: Path, cfg: VadConfig) -> list[SpeechSeg]:
    """Find speech spans in a 16 kHz mono wav.

    :param wav: audio file.
    :param cfg: VAD settings.
    :return: speech spans in seconds, in time order (empty if the audio has no speech).
    :raises PerceptionError: if VAD fails.
    """
    try:
        audio = read_wav(wav)
        stamps = get_speech_timestamps(
            audio,
            load_silero_vad(),
            sampling_rate=SAMPLE_RATE,
            threshold=cfg.threshold,
            min_speech_duration_ms=cfg.min_speech_ms,
            min_silence_duration_ms=cfg.min_silence_ms,
            speech_pad_ms=cfg.speech_pad_ms,
            return_seconds=False,
        )
    except Exception as exc:
        raise PerceptionError(f"VAD failed on {wav.name}") from exc
    return [SpeechSeg(start=s["start"] / SAMPLE_RATE, end=s["end"] / SAMPLE_RATE) for s in stamps]
