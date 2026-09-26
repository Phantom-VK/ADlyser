"""Command line: ``uv run python -m adlyser measure <video> --out data/<name>/``."""

import argparse
import asyncio
from pathlib import Path

from adlyser.config import get_settings
from adlyser.errors import PerceptionError
from adlyser.graph import run_pipeline
from adlyser.log import get_logger
from adlyser.perception.measure import measure_signals, measure_transcript
from adlyser.rules.candidates import find_candidates

log = get_logger("adlyser")


def cmd_measure(video: Path, out: Path) -> None:
    """Measure a video and write candidates.json, then add the transcript and write perception.json.

    Candidates are written before the transcript starts, so they never wait on whisper.

    :param video: path to the video.
    :param out: output directory.
    """
    settings = get_settings()
    out.mkdir(parents=True, exist_ok=True)
    perception = measure_signals(video, settings)
    result = find_candidates(perception.speech, perception.cuts, perception.duration_s, settings.candidates)
    (out / "candidates.json").write_text(result.model_dump_json(indent=1))
    (out / "perception.json").write_text(perception.model_dump_json(indent=1))
    hard = sum(c.kind == "hard" for c in perception.cuts)
    log.info(
        "measured",
        extra={
            "video": video.name,
            "minutes": round(perception.duration_s / 60, 1),
            "speech_spans": len(perception.speech),
            "hard_cuts": hard,
            "black_cuts": len(perception.cuts) - hard,
            **result.funnel.model_dump(),
            "candidates_json": out / "candidates.json",
        },
    )
    try:
        perception = measure_transcript(perception, settings)
    except PerceptionError as exc:
        log.error("transcript_failed", extra={"error": str(exc)})
    (out / "perception.json").write_text(perception.model_dump_json(indent=1))
    log.info(
        "done",
        extra={
            "transcript_segments": len(perception.transcript),
            "timings_s": perception.timings_s,
            "perception_json": out / "perception.json",
        },
    )


def cmd_run(video: Path, out: Path, base_url: str) -> None:
    """Run the whole pipeline: vmap.xml and debug.json in ``out``.

    :param video: path to the video.
    :param out: output directory.
    :param base_url: prefix for creative URLs; empty gives root-relative URLs for the local demo.
    """
    report = asyncio.run(run_pipeline(video, get_settings(), out, base_url))
    log.info(
        "run",
        extra={
            "vmap": out / "vmap.xml",
            "debug": out / "debug.json",
            "breaks": [(round(b.t, 1), b.outcome, b.brand_name) for b in report.breaks],
            "wall_s": report.wall_s,
        },
    )


def main() -> None:
    """Parse arguments and dispatch."""
    parser = argparse.ArgumentParser(prog="adlyser")
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("measure", help="perception + candidate pauses for one video")
    m.add_argument("video", type=Path)
    m.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("run", help="full pipeline -> vmap.xml + debug.json")
    r.add_argument("video", type=Path)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--base-url", default="")
    args = parser.parse_args()
    if args.command == "measure":
        cmd_measure(args.video, args.out)
    elif args.command == "run":
        cmd_run(args.video, args.out, args.base_url)


if __name__ == "__main__":
    main()
