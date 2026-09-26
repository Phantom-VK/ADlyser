"""BreakReviewer: (1) the safety sweep of a whole scene, (2) the review of one planned break."""

import asyncio
from pathlib import Path
from typing import Any

from adlyser.agents.tools import look_closer, speech_map
from adlyser.config import Settings
from adlyser.errors import PerceptionError
from adlyser.llm.agent_loop import run_agent
from adlyser.llm.client import LLMClient, user_message
from adlyser.llm.prompts import BREAK_REVIEWER, SAFETY_SWEEP, clock, scene_line, speech_text, with_schema
from adlyser.log import get_logger
from adlyser.perception.keyframes import boundary_times, extract_frames, sweep_times
from adlyser.schemas import Brand, Candidate, ReviewVerdict, Scene, SpeechSeg, SweepResult

log = get_logger(__name__)

SWEEP_FAILED = SweepResult(safety_tags=[], evidence="sweep unavailable", confidence=0.0)
REVIEW_FAILED = ReviewVerdict(decision="veto", reason="review unavailable", retry="promo")


async def sweep_scene(
    client: LLMClient, video: Path, frames_dir: Path, scene: Scene, settings: Settings
) -> SweepResult:
    """Look at frames across the FULL scene and list every safety tag seen. A failure has confidence 0.

    :param client: the vision client.
    :param video: path to the video.
    :param frames_dir: this video's frame cache directory.
    :param scene: the scene to sweep (its current tags are shown to the model).
    :param settings: loaded settings.
    :return: the sweep result, or ``SWEEP_FAILED``.
    """
    times = sweep_times(scene.start, scene.end, settings.reviewer)
    try:
        frames = await asyncio.to_thread(extract_frames, video, times, settings.frames, frames_dir)
    except PerceptionError as exc:
        log.error("sweep_frames_failed", extra={"scene": scene.index, "error": str(exc)[:200]})
        return SWEEP_FAILED
    stamps = ", ".join(clock(t) for t in times)
    tags = ", ".join(t.value for t in scene.safety_tags) or "none"
    text = (
        f"Scene {clock(scene.start)} to {clock(scene.end)}. {len(times)} frames in time order, "
        f"taken at {stamps}.\nCurrent tags: {tags}."
    )
    messages = [
        {"role": "system", "content": with_schema(SAFETY_SWEEP, SweepResult)},
        user_message(text, frames, client.endpoint.image_detail),
    ]
    return await client.chat_json("safety_sweep", messages, SweepResult, SWEEP_FAILED)


async def review_break(
    client: LLMClient,
    video: Path,
    frames_dir: Path,
    speech: list[SpeechSeg],
    duration_s: float,
    cand: Candidate,
    before: Scene,
    after: Scene,
    brand: Brand,
    settings: Settings,
) -> tuple[ReviewVerdict, list[dict[str, Any]]]:
    """Review one planned break with its brand. A failure vetoes with ``promo`` (never an unverified brand).

    :param client: the vision client.
    :param video: path to the video.
    :param frames_dir: this video's frame cache directory.
    :param speech: the measured speech map.
    :param duration_s: video length in seconds.
    :param cand: the candidate pause.
    :param before: the scene before, with sweep-added tags.
    :param after: the scene after, with sweep-added tags.
    :param brand: the chosen brand.
    :param settings: loaded settings.
    :return: ``(verdict, trace of tool calls)``.
    """
    times = boundary_times(cand.t, settings.boundary, duration_s)
    try:
        frames = await asyncio.to_thread(extract_frames, video, times, settings.frames, frames_dir)
    except PerceptionError as exc:
        log.error("review_frames_failed", extra={"t": round(cand.t, 1), "error": str(exc)[:200]})
        return REVIEW_FAILED, []
    window = settings.reviewer.speech_window_s
    text = (
        f"Break at {clock(cand.t)} ({cand.t:.0f}s). Silence {cand.silence_s:.1f} s, cut type {cand.kind}. "
        f"Frames: 2 before, then 2 after.\n"
        f"Scene before: {scene_line(before)}\nScene after: {scene_line(after)}\n"
        f"{speech_text(speech, cand.t - window, cand.t + window)}\n"
        f"Chosen brand: {brand.name} ({brand.category}). {brand.description}\n"
        f"Brand says it must NOT appear after: {'; '.join(brand.negative_contexts_raw) or 'nothing stated'}"
    )
    messages = [
        {"role": "system", "content": with_schema(BREAK_REVIEWER, ReviewVerdict)},
        user_message(text, frames, client.endpoint.image_detail),
    ]
    tools = [look_closer(video, frames_dir, settings.frames, duration_s), speech_map(speech)]
    return await run_agent(
        client, "break_reviewer", messages, tools, ReviewVerdict, REVIEW_FAILED, settings.reviewer.tool_rounds
    )
