"""Bengali transcript with faster-whisper (context for the AI only, never a rule input)."""

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from adlyser.config import TranscribeConfig, get_settings
from adlyser.errors import PerceptionError
from adlyser.log import get_logger
from adlyser.schemas import SpeechSeg, TranscriptSeg

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

log = get_logger(__name__)


def _load(cfg: TranscribeConfig) -> "WhisperModel":
    """Load the model on the configured device, falling back to CPU int8 if that fails."""
    from faster_whisper import WhisperModel  # lazy: keep ctranslate2 out of processes that use torch

    try:
        return WhisperModel(cfg.model_size, device=cfg.device, compute_type=cfg.compute_type)
    except Exception as exc:  # noqa: BLE001 - e.g. missing CUDA libs; never depend on a GPU
        log.warning("whisper_fallback_cpu", extra={"device": cfg.device, "error": str(exc)[:120]})
        return WhisperModel(cfg.model_size, device="cpu", compute_type="int8")


def clip_timestamps(speech: list[SpeechSeg], merge_gap_s: float) -> list[float]:
    """Turn speech spans into whisper ``clip_timestamps`` (flat start, end, start, end ...).

    :param speech: VAD speech spans.
    :param merge_gap_s: spans closer than this are merged into one clip.
    :return: flat list of seconds; empty if there is no speech.
    """
    merged: list[list[float]] = []
    for seg in sorted(speech, key=lambda s: s.start):
        if merged and seg.start - merged[-1][1] < merge_gap_s:
            merged[-1][1] = max(merged[-1][1], seg.end)
        else:
            merged.append([seg.start, seg.end])
    return [t for clip in merged for t in clip]


def transcribe(wav: Path, cfg: TranscribeConfig, speech: list[SpeechSeg]) -> list[TranscriptSeg]:
    """Transcribe only the VAD speech spans (no word timestamps).

    :param wav: 16 kHz mono audio.
    :param cfg: model size, device, compute type, language.
    :param speech: VAD speech spans; nothing outside them is decoded.
    :return: transcript segments (empty if there is no speech or nothing was recognised).
    :raises PerceptionError: if transcription fails.
    """
    clips = clip_timestamps(speech, cfg.clip_merge_gap_s)
    if not clips:
        return []
    try:
        model = _load(cfg)
        segments, _ = model.transcribe(
            str(wav),
            language=cfg.language,
            beam_size=cfg.beam_size,
            word_timestamps=False,
            clip_timestamps=clips,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        return [TranscriptSeg(start=float(s.start), end=float(s.end), text=s.text.strip()) for s in segments]
    except Exception as exc:
        raise PerceptionError(f"transcription failed on {wav.name}") from exc


def main() -> None:
    """Run as ``python -m adlyser.perception.transcribe <wav> <speech.json> <out.json>`` (used by ``measure``).

    Runs in its own process because torch (VAD) and ctranslate2 (whisper) must not share one.
    """
    wav, speech_json, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    speech = [SpeechSeg.model_validate(x) for x in json.loads(speech_json.read_text())]
    segments = transcribe(wav, get_settings().transcribe, speech)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps([s.model_dump(mode="json") for s in segments], ensure_ascii=False))
    tmp.replace(out)


if __name__ == "__main__":
    main()
