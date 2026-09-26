"""Pull JPEG frames from the video for the vision model. Frames are cached on disk."""

import math
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from adlyser.cache import unique_tmp
from adlyser.config import BoundaryConfig, FramesConfig, ReviewerConfig, StretchConfig
from adlyser.errors import PerceptionError
from adlyser.log import get_logger

log = get_logger(__name__)
_EDGE_S = 0.1  # stay this far from the end of the video, where a seek can return no frame


def stretch_times(start: float, end: float, cfg: StretchConfig) -> list[float]:
    """Times of the frames that represent one stretch, spread evenly across it.

    :param start: stretch start in seconds.
    :param end: stretch end in seconds.
    :param cfg: how many frames per stretch.
    :return: frame times in order, all strictly inside the stretch.
    """
    n = min(cfg.max_frames, max(cfg.min_frames, round((end - start) / cfg.frame_interval_s)))
    return [start + (end - start) * (i + 0.5) / n for i in range(n)]


def sweep_times(start: float, end: float, cfg: ReviewerConfig) -> list[float]:
    """Times of the safety-sweep frames across a WHOLE scene: about one per interval, capped.

    :param start: scene start in seconds.
    :param end: scene end in seconds.
    :param cfg: sweep interval and frame cap.
    :return: frame times in order, spread evenly and strictly inside the scene.
    """
    n = min(cfg.sweep_max_frames, max(1, math.ceil((end - start) / cfg.sweep_interval_s)))
    return [start + (end - start) * (i + 0.5) / n for i in range(n)]


def sweep_covers_scene(start: float, end: float, cfg: ReviewerConfig) -> bool:
    """Whether the sweep frame cap still allows one frame per interval across the whole scene.

    :param start: scene start in seconds.
    :param end: scene end in seconds.
    :param cfg: sweep interval and frame cap.
    :return: false when the cap thinned the frames below the configured interval.
    """
    return math.ceil((end - start) / cfg.sweep_interval_s) <= cfg.sweep_max_frames


def boundary_times(t: float, cfg: BoundaryConfig, duration_s: float) -> list[float]:
    """Times of the frames around a cut: the offsets before it, then the same offsets after it.

    :param t: the cut time in seconds.
    :param cfg: offsets from the cut, largest first.
    :param duration_s: video length, used to clamp.
    :return: frame times in order.
    """
    offsets = cfg.frame_offsets_s
    times = [t - o for o in offsets] + [t + o for o in reversed(offsets)]
    return [min(max(x, 0.0), duration_s - _EDGE_S) for x in times]


def _extract(video: Path, t: float, cfg: FramesConfig) -> bytes:
    """Decode one frame with ffmpeg (fast seek) and return it as JPEG bytes."""
    cmd = [
        "ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
        "-vf", f"scale={cfg.width}:-2", "-q:v", str(cfg.jpeg_quality),
        "-f", "image2pipe", "-c:v", "mjpeg", "-",
    ]  # fmt: skip
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0 or not proc.stdout:
        raise PerceptionError(f"no frame at {t:.1f}s in {video.name}: {proc.stderr.decode()[:200]}")
    return proc.stdout


def extract_frames(video: Path, times: list[float], cfg: FramesConfig, cache_dir: Path) -> list[bytes]:
    """Get one JPEG per time, in order, reading from and writing to the frame cache.

    :param video: path to the video.
    :param times: frame times in seconds.
    :param cfg: frame size and quality.
    :param cache_dir: directory for this video's cached frames.
    :return: JPEG bytes, one per time.
    :raises PerceptionError: if a frame cannot be decoded.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)

    def one(t: float) -> bytes:
        path = cache_dir / f"{round(t * 1000)}_w{cfg.width}_q{cfg.jpeg_quality}.jpg"
        if path.exists():
            return path.read_bytes()
        jpg = _extract(video, t, cfg)
        tmp = unique_tmp(path)
        tmp.write_bytes(jpg)
        tmp.replace(path)
        return jpg

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(one, times))
