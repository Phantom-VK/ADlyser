"""Read-only tools agents may call. They return evidence (frames, text) and never write a decision."""

import asyncio
from pathlib import Path
from typing import Any

from adlyser.config import FramesConfig
from adlyser.errors import PerceptionError
from adlyser.llm.agent_loop import Tool
from adlyser.perception.keyframes import extract_frames

MAX_LOOK_FRAMES = 6

_LOOK_CLOSER_SPEC = {
    "type": "function",
    "function": {
        "name": "look_closer",
        "description": (
            "Get n more frames evenly spread between t0 and t1, in seconds from the start of the episode."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "t0": {"type": "number"},
                "t1": {"type": "number"},
                "n": {"type": "integer", "minimum": 1, "maximum": MAX_LOOK_FRAMES},
            },
            "required": ["t0", "t1", "n"],
        },
    },
}


def look_closer(video: Path, frames_dir: Path, cfg: FramesConfig, duration_s: float) -> Tool:
    """Build the ``look_closer`` tool for one video.

    :param video: path to the video.
    :param frames_dir: this video's frame cache directory.
    :param cfg: frame size and quality.
    :param duration_s: video length; requested times are clamped into it.
    :return: the tool.
    """

    async def run(args: dict[str, Any]) -> tuple[str, list[bytes]]:
        """Extract the requested frames (clamped to the video and to ``MAX_LOOK_FRAMES``)."""
        n = max(1, min(int(args["n"]), MAX_LOOK_FRAMES))
        lo = max(0.0, min(float(args["t0"]), float(args["t1"])))
        hi = min(duration_s - 0.1, max(float(args["t0"]), float(args["t1"])))
        if hi <= lo:
            raise PerceptionError("empty time range")
        times = [lo + (hi - lo) * (i + 0.5) / n for i in range(n)]
        frames = await asyncio.to_thread(extract_frames, video, times, cfg, frames_dir)
        return f"{n} frames follow, taken at {', '.join(f'{t:.0f}s' for t in times)}.", frames

    return Tool(spec=_LOOK_CLOSER_SPEC, run=run, detail="high")
