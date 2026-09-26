"""StretchAnalyst: one vision call per stretch, optionally with a bounded ``look_closer`` tool loop."""

import asyncio
from pathlib import Path
from typing import Any

from adlyser.agents.tools import look_closer
from adlyser.config import Settings
from adlyser.errors import PerceptionError
from adlyser.llm.agent_loop import run_agent
from adlyser.llm.client import LLMClient, user_message
from adlyser.llm.prompts import STRETCH_ANALYST, STRETCH_TOOLS, stretch_text, transcript_text, with_schema
from adlyser.log import get_logger
from adlyser.perception.keyframes import extract_frames, stretch_times
from adlyser.schemas import Stretch, StretchAnalysis, TranscriptSeg

log = get_logger(__name__)

UNKNOWN = StretchAnalysis(
    summary="analysis unavailable",
    dominant_activity="unknown",
    setting="unknown",
    mood="unknown",
    safety_tags=[],
    confidence=0.0,
)


async def analyse_stretch(
    client: LLMClient,
    video: Path,
    frames_dir: Path,
    stretch: Stretch,
    transcript: list[TranscriptSeg],
    duration_s: float,
    settings: Settings,
) -> tuple[StretchAnalysis, list[dict[str, Any]]]:
    """Describe one stretch. Any failure returns ``UNKNOWN`` (confidence 0), which blocks every brand.

    :param client: the vision client.
    :param video: path to the video.
    :param frames_dir: this video's frame cache directory.
    :param stretch: the stretch to analyse.
    :param transcript: transcript segments (may be empty).
    :param duration_s: video length in seconds.
    :param settings: loaded settings.
    :return: ``(analysis or UNKNOWN, trace of look_closer calls)``.
    """
    times = stretch_times(stretch.start, stretch.end, settings.stretch)
    try:
        frames = await asyncio.to_thread(extract_frames, video, times, settings.frames, frames_dir)
    except PerceptionError as exc:
        log.error("stretch_frames_failed", extra={"stretch": stretch.index, "error": str(exc)[:200]})
        return UNKNOWN, []
    rounds = settings.stretch.tool_rounds
    text = stretch_text(stretch, times, transcript_text(transcript, stretch.start, stretch.end), rounds > 0)
    system = with_schema(STRETCH_ANALYST + (STRETCH_TOOLS if rounds > 0 else ""), StretchAnalysis)
    messages = [
        {"role": "system", "content": system},
        user_message(text, frames, client.endpoint.image_detail),
    ]
    if rounds == 0:
        return await client.chat_json("stretch_analyst", messages, StretchAnalysis, UNKNOWN), []
    tools = [look_closer(video, frames_dir, settings.frames, duration_s)]
    return await run_agent(client, "stretch_analyst", messages, tools, StretchAnalysis, UNKNOWN, rounds)
