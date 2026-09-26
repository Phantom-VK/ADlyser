"""Audio extraction and probing with ffmpeg."""

import subprocess
from pathlib import Path

from adlyser.errors import PerceptionError


def probe_duration(video: Path) -> float:
    """Return the video duration in seconds.

    :param video: path to the video.
    :return: duration in seconds.
    :raises PerceptionError: if ffprobe fails or returns nonsense.
    """
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
            capture_output=True,
            text=True,
            check=True,
        )
        duration = float(out.stdout.strip())
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as exc:
        raise PerceptionError(f"cannot read duration of {video.name}") from exc
    if duration <= 0:
        raise PerceptionError(f"{video.name} has no duration")
    return duration


def extract_wav(video: Path, wav: Path) -> Path:
    """Extract 16 kHz mono PCM audio. Written to a temp file then renamed, so a killed run never leaves a truncated wav.

    :param video: source video.
    :param wav: destination wav path (parent is created).
    :return: the wav path.
    :raises PerceptionError: if the video has no audio or ffmpeg fails.
    """
    wav.parent.mkdir(parents=True, exist_ok=True)
    tmp = wav.with_name(wav.name + ".tmp")
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000"]
    try:
        subprocess.run(
            [*cmd, "-c:a", "pcm_s16le", "-f", "wav", str(tmp)], capture_output=True, text=True, check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        tmp.unlink(missing_ok=True)
        detail = getattr(exc, "stderr", "") or ""
        raise PerceptionError(f"audio extraction failed for {video.name}: {detail[:200]}") from exc
    if tmp.stat().st_size < 1000:
        tmp.unlink(missing_ok=True)
        raise PerceptionError(f"{video.name} has no usable audio track")
    tmp.replace(wav)
    return wav
