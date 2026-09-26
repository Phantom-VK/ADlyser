"""Bengali transcript with faster-whisper (context for the AI only, never a rule input)."""

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from adlyser.config import TranscribeConfig, get_settings
from adlyser.errors import PerceptionError
from adlyser.log import get_logger
from adlyser.schemas import TranscriptSeg, Word

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


def transcribe(wav: Path, cfg: TranscribeConfig) -> list[TranscriptSeg]:
    """Transcribe a wav with word timestamps.

    :param wav: 16 kHz mono audio.
    :param cfg: model size, device, compute type, language.
    :return: transcript segments (empty if nothing was recognised).
    :raises PerceptionError: if transcription fails.
    """
    try:
        model = _load(cfg)
        segments, _ = model.transcribe(
            str(wav),
            language=cfg.language,
            beam_size=cfg.beam_size,
            word_timestamps=True,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        return [
            TranscriptSeg(
                start=float(s.start),
                end=float(s.end),
                text=s.text.strip(),
                words=[
                    Word(start=float(w.start), end=float(w.end), text=w.word.strip()) for w in s.words or []
                ],
            )
            for s in segments
        ]
    except Exception as exc:
        raise PerceptionError(f"transcription failed on {wav.name}") from exc


def main() -> None:
    """Run as ``python -m adlyser.perception.transcribe <wav> <out.json>`` (used by ``measure``).

    Runs in its own process because torch (VAD) and ctranslate2 (whisper) must not share one.
    """
    wav, out = Path(sys.argv[1]), Path(sys.argv[2])
    segments = transcribe(wav, get_settings().transcribe)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps([s.model_dump(mode="json") for s in segments], ensure_ascii=False))
    tmp.replace(out)


if __name__ == "__main__":
    main()
