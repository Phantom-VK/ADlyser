"""Measure one video. Candidates never wait on the transcript.

Order: audio -> VAD -> cuts (hard and black in parallel) -> [candidates] -> transcript (own process).
Every stage is cached by video fingerprint + its settings.
"""

import json
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel

from adlyser.cache import DiskCache, content_key, file_fingerprint
from adlyser.config import Settings
from adlyser.errors import PerceptionError
from adlyser.log import get_logger
from adlyser.perception.audio import extract_wav, probe_duration
from adlyser.perception.cuts import detect_black, detect_hard_cuts
from adlyser.perception.speech import detect_speech
from adlyser.schemas import Cut, Perception, SpeechSeg, TranscriptSeg

log = get_logger(__name__)


def _stage[M: BaseModel](
    cache: DiskCache,
    stage: str,
    key: str,
    model: type[M],
    fn: Callable[[], list[M]],
    timings: dict[str, float],
) -> list[M]:
    """Run one measurement stage through the disk cache and record its wall time."""
    hit = cache.get(stage, key)
    if hit is not None:
        timings[stage] = 0.0
        log.info("stage", extra={"stage": stage, "cached": True})
        return [model.model_validate(x) for x in hit]
    start = time.perf_counter()
    out = fn()
    timings[stage] = round(time.perf_counter() - start, 1)
    cache.set(stage, key, [x.model_dump(mode="json") for x in out])
    log.info("stage", extra={"stage": stage, "cached": False, "s": timings[stage], "n": len(out)})
    return out


def wav_path(settings: Settings, fingerprint: str) -> Path:
    """Where the extracted audio of a video lives.

    :param settings: loaded settings.
    :param fingerprint: the video fingerprint.
    :return: the wav path.
    """
    return settings.cache_dir / "perception" / "audio" / f"{fingerprint}.wav"


def measure_signals(video: Path, settings: Settings) -> Perception:
    """Measure everything the candidate rule needs: speech map and cuts (no transcript).

    :param video: path to the video file.
    :param settings: loaded settings.
    :return: measurements with an empty transcript.
    :raises PerceptionError: if a stage fails.
    """
    fingerprint = file_fingerprint(video)
    duration = probe_duration(video)
    cache = DiskCache(settings.cache_dir / "perception")
    wav = wav_path(settings, fingerprint)
    timings: dict[str, float] = {}

    if not wav.exists():
        start = time.perf_counter()
        extract_wav(video, wav)
        timings["audio"] = round(time.perf_counter() - start, 1)

    def key(stage: str, params: dict) -> str:
        return content_key(fingerprint, stage, params)

    speech = _stage(
        cache, "speech", key("speech", settings.vad.model_dump()), SpeechSeg,
        lambda: detect_speech(wav, settings.vad), timings,
    )  # fmt: skip
    cuts_key = key("cuts", settings.cuts.model_dump())
    with ThreadPoolExecutor(max_workers=2) as pool:
        hard = pool.submit(
            _stage, cache, "cuts_hard", cuts_key, Cut, lambda: detect_hard_cuts(video, settings.cuts), timings
        )
        black = pool.submit(
            _stage, cache, "cuts_black", cuts_key, Cut, lambda: detect_black(video, settings.cuts), timings
        )
        cuts = sorted([*hard.result(), *black.result()], key=lambda c: c.t)

    return Perception(
        video=video.name,
        fingerprint=fingerprint,
        duration_s=duration,
        speech=speech,
        cuts=cuts,
        transcript=[],
        timings_s=timings,
    )


def _transcribe_subprocess(wav: Path) -> list[TranscriptSeg]:
    """Transcribe in a fresh process (torch and ctranslate2 must not share one)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "transcript.json"
        proc = subprocess.run(
            [sys.executable, "-m", "adlyser.perception.transcribe", str(wav), str(out)], check=False
        )
        if proc.returncode != 0 or not out.exists():
            raise PerceptionError(f"transcription process failed for {wav.name} (exit {proc.returncode})")
        return [TranscriptSeg.model_validate(x) for x in json.loads(out.read_text())]


def measure_transcript(perception: Perception, settings: Settings) -> Perception:
    """Add the transcript (cached). Run this after candidates are written.

    :param perception: result of ``measure_signals``.
    :param settings: loaded settings.
    :return: a copy of ``perception`` with the transcript and its timing filled in.
    :raises PerceptionError: if transcription fails.
    """
    cache = DiskCache(settings.cache_dir / "perception")
    tcfg = settings.transcribe
    key = content_key(
        perception.fingerprint, "transcript", tcfg.model_dump(exclude={"device", "compute_type"})
    )
    timings = dict(perception.timings_s)
    wav = wav_path(settings, perception.fingerprint)
    transcript = _stage(cache, "transcript", key, TranscriptSeg, lambda: _transcribe_subprocess(wav), timings)
    return perception.model_copy(update={"transcript": transcript, "timings_s": timings})
