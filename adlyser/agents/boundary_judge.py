"""BoundaryJudge: one vision call per candidate pause (single call)."""

import asyncio
from pathlib import Path

from adlyser.config import Settings
from adlyser.errors import PerceptionError
from adlyser.llm.client import LLMClient, user_message
from adlyser.llm.prompts import BOUNDARY_JUDGE, boundary_text, transcript_text, with_schema
from adlyser.log import get_logger
from adlyser.perception.keyframes import boundary_times, extract_frames
from adlyser.schemas import BoundaryVerdict, Candidate, StretchAnalysis, TranscriptSeg

log = get_logger(__name__)

NOT_A_BREAK = BoundaryVerdict(is_scene_change=False, break_score=0.0, reason="judgement unavailable")


async def judge_boundary(
    client: LLMClient,
    video: Path,
    frames_dir: Path,
    cand: Candidate,
    before: StretchAnalysis,
    after: StretchAnalysis,
    transcript: list[TranscriptSeg],
    duration_s: float,
    settings: Settings,
) -> BoundaryVerdict:
    """Decide whether a candidate is a real scene change and how good a break it is.

    Any failure returns ``NOT_A_BREAK``: dropping a break is always safe.

    :param client: the vision client.
    :param video: path to the video.
    :param frames_dir: this video's frame cache directory.
    :param cand: the candidate pause.
    :param before: analysis of the stretch before the cut.
    :param after: analysis of the stretch after the cut.
    :param transcript: transcript segments (may be empty).
    :param duration_s: video length in seconds.
    :param settings: loaded settings.
    :return: the validated verdict, or ``NOT_A_BREAK``.
    """
    times = boundary_times(cand.t, settings.boundary, duration_s)
    try:
        frames = await asyncio.to_thread(extract_frames, video, times, settings.frames, frames_dir)
    except PerceptionError as exc:
        log.error("boundary_frames_failed", extra={"t": round(cand.t, 1), "error": str(exc)[:200]})
        return NOT_A_BREAK
    around = transcript_text(transcript, cand.t - 20, cand.t + 20)
    text = boundary_text(cand, before.summary, after.summary, around)
    messages = [
        {"role": "system", "content": with_schema(BOUNDARY_JUDGE, BoundaryVerdict)},
        user_message(text, frames, client.endpoint.image_detail),
    ]
    return await client.chat_json("boundary_judge", messages, BoundaryVerdict, NOT_A_BREAK)
