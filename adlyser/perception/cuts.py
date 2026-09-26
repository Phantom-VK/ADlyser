"""Visual transitions: hard shot cuts (PySceneDetect) and fades to black (ffmpeg blackdetect)."""

import re
import subprocess
from pathlib import Path

from scenedetect import AdaptiveDetector, SceneManager, open_video

from adlyser.config import CutsConfig
from adlyser.errors import PerceptionError
from adlyser.schemas import Cut

_BLACK = re.compile(r"black_start:(\S+)\s+black_end:(\S+)")


def detect_hard_cuts(video: Path, cfg: CutsConfig) -> list[Cut]:
    """Detect hard shot cuts with the adaptive detector (frames are auto-downscaled).

    :param video: source video.
    :param cfg: detector settings.
    :return: cuts in time order.
    :raises PerceptionError: if detection fails.
    """
    try:
        manager = SceneManager()
        manager.add_detector(
            AdaptiveDetector(
                adaptive_threshold=cfg.adaptive_threshold, min_scene_len=cfg.min_scene_len_frames
            )
        )
        manager.detect_scenes(open_video(str(video)))
        scenes = manager.get_scene_list()
    except Exception as exc:
        raise PerceptionError(f"shot detection failed on {video.name}") from exc
    return [Cut(t=float(start.get_seconds()), kind="hard") for start, _ in scenes[1:]]


def detect_black(video: Path, cfg: CutsConfig) -> list[Cut]:
    """Detect fades to black; each black interval yields one cut at its middle.

    :param video: source video.
    :param cfg: black-frame settings.
    :return: cuts in time order.
    :raises PerceptionError: if ffmpeg fails.
    """
    vf = (
        f"scale={cfg.black_scale_width}:-2,"
        f"blackdetect=d={cfg.black_min_duration_s}:pix_th={cfg.black_pixel_threshold}"
    )
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-an", "-vf", vf, "-f", "null", "-"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise PerceptionError(f"blackdetect failed on {video.name}") from exc
    cuts = [Cut(t=(float(a) + float(b)) / 2, kind="black") for a, b in _BLACK.findall(proc.stderr)]
    return sorted(cuts, key=lambda c: c.t)
