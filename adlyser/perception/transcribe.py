"""Bengali transcript, from faster-whisper or Groq (context for the AI only, never a rule input)."""

import hashlib
import json
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from adlyser.cache import DiskCache, content_key, unique_tmp
from adlyser.config import TranscribeConfig, get_settings
from adlyser.errors import PerceptionError
from adlyser.log import get_logger
from adlyser.schemas import SpeechSeg, TranscriptSeg

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

log = get_logger(__name__)


class RateLimited(PerceptionError):
    """The transcript provider answered 429. ``retry_after_s`` is how long it asked us to wait."""

    def __init__(self, message: str, retry_after_s: float) -> None:
        """Create the error.

        :param message: what was rate limited.
        :param retry_after_s: seconds until the provider will accept a request again.
        """
        super().__init__(message)
        self.retry_after_s = retry_after_s


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


def _overlap_s(start: float, end: float, speech: list[SpeechSeg]) -> float:
    """Seconds of VAD speech under ``[start, end]``."""
    return sum(max(0.0, min(end, s.end) - max(start, s.start)) for s in speech)


def make_chunks(
    duration_s: float, speech: list[SpeechSeg], cfg: TranscribeConfig, cut: Callable[[float, float], bytes]
) -> list[tuple[float, bytes]]:
    """Cut the audio into windows of about ``chunk_s`` and skip the windows with no speech.

    A window whose audio is over ``max_chunk_mb`` is halved (down to ``chunk_min_s``), so no request is too big.

    :param duration_s: audio length in seconds.
    :param speech: VAD speech spans.
    :param cfg: transcript settings.
    :param cut: ``cut(start_s, length_s)`` returns that stretch as flac bytes.
    :return: ``(offset_s, flac bytes)`` in time order.
    """
    chunks: list[tuple[float, bytes]] = []

    def add(start: float, length: float) -> None:
        end = min(start + length, duration_s)
        if not any(s.end > start and s.start < end for s in speech):
            return
        data = cut(start, end - start)
        if len(data) > cfg.max_chunk_mb * 1e6 and (end - start) / 2 >= cfg.chunk_min_s:
            half = (end - start) / 2
            add(start, half)
            add(start + half, half)
        else:
            chunks.append((start, data))

    start = 0.0
    while start < duration_s:
        add(start, cfg.chunk_s)
        start += cfg.chunk_s
    return chunks


def _ask(
    client: Any,
    name: str,
    data: bytes,
    cfg: TranscribeConfig,
    wait_on_limit: bool,
    sleep: Callable[[float], None],
) -> list[dict[str, Any]]:
    """One transcription request; on a 429 either raise ``RateLimited`` or wait for retry-after and try again."""
    import groq

    for attempt in range(1, cfg.retry_attempts + 1):
        try:
            reply = client.audio.transcriptions.create(
                file=(name, data),
                model=cfg.model,
                temperature=0,
                response_format="verbose_json",
                language=cfg.language,
            )
            return list(
                (reply.model_dump() if hasattr(reply, "model_dump") else dict(reply)).get("segments") or []
            )
        except groq.RateLimitError as exc:
            header = exc.response.headers.get("retry-after") if exc.response is not None else None
            try:
                wait = float(header) if header else cfg.retry_default_wait_s
            except ValueError:
                wait = cfg.retry_default_wait_s
            wait = min(wait, cfg.retry_max_wait_s)
            if not wait_on_limit or attempt == cfg.retry_attempts:
                raise RateLimited("transcript rate limit reached", wait) from exc
            log.warning("groq_rate_limited", extra={"wait_s": wait, "attempt": attempt})
            sleep(wait)
        except groq.APIError as exc:
            raise PerceptionError(f"transcript request failed: {type(exc).__name__}") from exc
    raise PerceptionError("transcript request failed")  # unreachable: the last attempt raises above


def transcribe_groq(
    chunks: list[tuple[float, bytes]],
    client: Any,
    cfg: TranscribeConfig,
    speech: list[SpeechSeg],
    cache: DiskCache,
    *,
    wait_on_limit: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> list[TranscriptSeg]:
    """Transcribe audio chunks with Groq and keep only segments that are plausibly speech.

    Each chunk's raw answer is cached by the hash of its audio, model and language. A segment is dropped
    if the model's own ``no_speech_prob`` is over ``max_no_speech_prob``, or if less than ``min_overlap_s``
    of VAD speech lies under it (a hallucination guard). Kept times are shifted by the chunk offset.

    :param chunks: ``(offset_s, flac bytes)`` per chunk.
    :param client: a Groq client (or anything with ``audio.transcriptions.create``).
    :param cfg: transcript settings.
    :param speech: VAD speech spans in video time.
    :param cache: where raw answers are kept.
    :param wait_on_limit: on a 429, wait for retry-after and retry (precompute) instead of raising (live run).
    :param sleep: how to wait (replaced in tests).
    :return: transcript segments in time order.
    :raises RateLimited: on a 429 that is not waited out.
    :raises PerceptionError: on any other request failure.
    """
    kept: list[TranscriptSeg] = []
    requests = cached = no_speech = outside_vad = 0
    for offset, data in chunks:
        key = content_key(hashlib.sha256(data).hexdigest(), cfg.model, cfg.language)
        raw = cache.get("groq", key)
        if raw is None:
            raw = _ask(client, f"chunk_{offset:.0f}.flac", data, cfg, wait_on_limit, sleep)
            raw = [{k: seg.get(k) for k in ("start", "end", "text", "no_speech_prob")} for seg in raw]
            cache.set("groq", key, raw)
            requests += 1
        else:
            cached += 1
        for seg in raw:
            start, end, text = (
                offset + float(seg["start"]),
                offset + float(seg["end"]),
                str(seg["text"]).strip(),
            )
            if not text:
                continue
            if float(seg.get("no_speech_prob") or 0.0) > cfg.max_no_speech_prob:
                no_speech += 1
            elif _overlap_s(start, end, speech) < cfg.min_overlap_s:
                outside_vad += 1
            else:
                kept.append(TranscriptSeg(start=start, end=end, text=text))
    log.info(
        "groq_transcript",
        extra={"chunks": len(chunks), "requests": requests, "cached": cached, "kept": len(kept),
               "dropped_no_speech": no_speech, "dropped_outside_vad": outside_vad},
    )  # fmt: skip
    return sorted(kept, key=lambda s: s.start)


def _cut_flac(wav: Path, start: float, length: float) -> bytes:
    """``length`` seconds of ``wav`` from ``start`` as mono 16 kHz flac bytes."""
    cmd = ["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(length), "-i", str(wav)]
    try:
        done = subprocess.run(
            [*cmd, "-ac", "1", "-ar", "16000", "-f", "flac", "-"], capture_output=True, check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise PerceptionError(f"cannot cut audio from {wav.name}") from exc
    return done.stdout


def transcribe_with_groq(
    wav: Path,
    duration_s: float,
    cfg: TranscribeConfig,
    speech: list[SpeechSeg],
    api_key: str,
    cache: DiskCache,
    wait_on_limit: bool = False,
) -> list[TranscriptSeg]:
    """Transcribe a whole wav through Groq in ``chunk_s`` windows.

    :param wav: 16 kHz mono audio of the whole video.
    :param duration_s: its length in seconds.
    :param cfg: transcript settings.
    :param speech: VAD speech spans; windows with no speech are never sent.
    :param api_key: ``GROQ_API_KEY`` (never logged).
    :param cache: where raw answers are kept.
    :param wait_on_limit: wait out a rate limit instead of failing.
    :return: transcript segments (empty if there is no speech).
    :raises PerceptionError: without a key, or if a request fails (``RateLimited`` on a 429).
    """
    if not speech:
        return []
    if not api_key:
        raise PerceptionError("GROQ_API_KEY is not set")
    import groq

    client = groq.Groq(
        api_key=api_key, timeout=cfg.request_timeout_s, max_retries=0
    )  # 429s are ours to handle
    chunks = make_chunks(duration_s, speech, cfg, lambda start, length: _cut_flac(wav, start, length))
    return transcribe_groq(chunks, client, cfg, speech, cache, wait_on_limit=wait_on_limit)


def main() -> None:
    """Run as ``python -m adlyser.perception.transcribe <wav> <speech.json> <out.json>`` (used by ``measure``).

    Runs in its own process because torch (VAD) and ctranslate2 (whisper) must not share one.
    """
    wav, speech_json, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    speech = [SpeechSeg.model_validate(x) for x in json.loads(speech_json.read_text())]
    segments = transcribe(wav, get_settings().transcribe, speech)
    tmp = unique_tmp(out)
    tmp.write_text(json.dumps([s.model_dump(mode="json") for s in segments], ensure_ascii=False))
    tmp.replace(out)


if __name__ == "__main__":
    main()
