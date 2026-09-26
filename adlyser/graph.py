"""Pipeline stages wired in order: measure -> candidates -> stretches -> boundaries -> scenes -> pacing.

Plain async functions for now; LangGraph wrapping comes with the branching stages (reviewer loop).
"""

import asyncio
import time
from pathlib import Path

from adlyser.agents.boundary_judge import judge_boundary
from adlyser.agents.stretch_analyst import analyse_stretch
from adlyser.cache import file_fingerprint
from adlyser.config import Settings
from adlyser.llm.client import make_clients
from adlyser.log import get_logger
from adlyser.perception.measure import measure_signals
from adlyser.rules.candidates import find_candidates
from adlyser.rules.pacing import select_breaks
from adlyser.rules.scenes import build_scenes, make_stretches
from adlyser.schemas import Analysis, BreakOption

log = get_logger(__name__)


async def run_analysis(video: Path, settings: Settings) -> Analysis:
    """Run the pipeline on one video, up to the chosen breaks.

    :param video: path to the video.
    :param settings: loaded settings.
    :return: every intermediate decision plus the chosen breaks.
    :raises AdlyserError: if measurement fails (individual LLM failures fall back safely instead).
    """
    start = time.perf_counter()
    perception = await asyncio.to_thread(measure_signals, video, settings)
    found = find_candidates(perception.speech, perception.cuts, perception.duration_s, settings.candidates)
    cands = found.candidates
    stretches = make_stretches(cands, perception.duration_s)
    vision, _text = make_clients(settings)
    frames_dir = settings.cache_dir / "frames" / file_fingerprint(video)

    stretch_results = await asyncio.gather(
        *[
            analyse_stretch(
                vision, video, frames_dir, s, perception.transcript, perception.duration_s, settings
            )
            for s in stretches
        ]
    )
    analyses = [a for a, _ in stretch_results]
    traces = [t for _, t in stretch_results]
    verdicts = await asyncio.gather(
        *[
            judge_boundary(
                vision,
                video,
                frames_dir,
                cand,
                analyses[i],
                analyses[i + 1],
                perception.transcript,
                perception.duration_s,
                settings,
            )
            for i, cand in enumerate(cands)
        ]
    )
    scenes = build_scenes(
        stretches, analyses, [v.is_scene_change for v in verdicts], settings.scenes.min_confidence
    )
    options = [
        BreakOption(candidate=c, break_score=v.break_score)
        for c, v in zip(cands, verdicts, strict=True)
        if v.is_scene_change
    ]
    breaks = select_breaks(options, perception.duration_s, settings.pacing)
    wall_s = round(time.perf_counter() - start, 1)
    log.info(
        "analysis_done", extra={"stretches": len(stretches), "scenes": len(scenes), "breaks": len(breaks)}
    )
    return Analysis(
        video=video.name,
        duration_s=perception.duration_s,
        funnel=found.funnel,
        candidates=cands,
        stretches=stretches,
        analyses=analyses,
        stretch_traces=traces,
        verdicts=list(verdicts),
        scenes=scenes,
        breaks=breaks,
        llm_stats={k: dict(v) for k, v in vision.stats.items()},
        wall_s=wall_s,
    )
