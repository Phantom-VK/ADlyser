"""Command line: ``uv run python -m adlyser measure <video> --out data/<name>/``."""

import argparse
from pathlib import Path

from adlyser.config import get_settings
from adlyser.emit.creatives import make_slate
from adlyser.emit.vmap import build_vmap
from adlyser.errors import PerceptionError
from adlyser.log import get_logger
from adlyser.perception.measure import measure_signals, measure_transcript
from adlyser.rules.candidates import find_candidates
from adlyser.schemas import Creative
from adlyser.skeleton import pick_breaks, to_specs

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


def cmd_skeleton(video: Path, out: Path, base_url: str) -> None:
    """Walking skeleton: pick breaks, make the promo slate, write vmap.xml.

    :param video: path to the video.
    :param out: output directory (also receives vmap.xml).
    :param base_url: prefix for creative URLs; empty gives root-relative URLs for the local demo.
    """
    settings = get_settings()
    perception = measure_signals(video, settings)
    result = find_candidates(perception.speech, perception.cuts, perception.duration_s, settings.candidates)
    chosen = pick_breaks(result.candidates, perception.duration_s, settings.pacing)
    promo = settings.data_dir / "creatives" / "promo.mp4"
    if not promo.exists():
        make_slate(
            settings.creatives.promo_title, settings.creatives.promo_subtitle, promo, settings.creatives
        )
    creative = Creative(
        ad_id="promo",
        title=settings.creatives.promo_title,
        duration_s=settings.creatives.duration_s,
        media_url=f"{base_url}/{promo.as_posix()}",
        width=settings.creatives.width,
        height=settings.creatives.height,
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / "vmap.xml").write_text(build_vmap(to_specs(chosen, creative)))
    log.info(
        "skeleton",
        extra={
            "breaks": [round(c.t, 1) for c in chosen],
            "vmap": out / "vmap.xml",
            "creative": creative.media_url,
        },
    )


def main() -> None:
    """Parse arguments and dispatch."""
    parser = argparse.ArgumentParser(prog="adlyser")
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("measure", help="perception + candidate pauses for one video")
    m.add_argument("video", type=Path)
    m.add_argument("--out", type=Path, required=True)
    k = sub.add_parser("skeleton", help="throwaway: longest-silence breaks + promo slate -> vmap.xml")
    k.add_argument("video", type=Path)
    k.add_argument("--out", type=Path, required=True)
    k.add_argument("--base-url", default="")
    args = parser.parse_args()
    if args.command == "measure":
        cmd_measure(args.video, args.out)
    elif args.command == "skeleton":
        cmd_skeleton(args.video, args.out, args.base_url)


if __name__ == "__main__":
    main()
