"""Phase 0 smoke test: multi-image input, JSON validity, latency/cost, and the tool loop.

Usage: uv run python scripts/smoke_llm.py <video> [<video> ...] [--seed N]
Stretches are picked at random offsets (seeded), never by watching the videos.
"""

import argparse
import asyncio
import json
import random
import subprocess
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from adlyser.config import get_settings
from adlyser.llm.client import LLMClient, image_part, make_clients, user_message
from adlyser.llm.prompts import BOUNDARY_JUDGE, STRETCH_ANALYST, with_schema
from adlyser.log import get_logger
from adlyser.schemas import BoundaryVerdict, StretchAnalysis

log = get_logger("smoke")
OUT = Path("data/smoke")

LOOK_CLOSER = {
    "type": "function",
    "function": {
        "name": "look_closer",
        "description": "Get n more frames evenly spread between t0 and t1 (seconds) of the episode.",
        "parameters": {
            "type": "object",
            "properties": {
                "t0": {"type": "number"},
                "t1": {"type": "number"},
                "n": {"type": "integer", "minimum": 1, "maximum": 6},
            },
            "required": ["t0", "t1", "n"],
        },
    },
}


def duration(video: Path) -> float:
    """Return the video duration in seconds.

    :param video: path to the video.
    :return: duration in seconds.
    """
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(out.stdout.strip())


def frame_at(video: Path, t: float, width: int = 640) -> bytes:
    """Extract one JPEG frame.

    :param video: path to the video.
    :param t: time in seconds.
    :param width: output width in pixels.
    :return: JPEG bytes.
    """
    out = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{t:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            f"scale={width}:-2",
            "-q:v",
            "5",
            "-f",
            "image2pipe",
            "-c:v",
            "mjpeg",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    return out.stdout


def frames_between(video: Path, t0: float, t1: float, n: int) -> list[tuple[float, bytes]]:
    """Extract n frames evenly spread inside [t0, t1].

    :param video: path to the video.
    :param t0: start seconds.
    :param t1: end seconds.
    :param n: number of frames.
    :return: list of (time, jpeg).
    """
    times = [t0 + (t1 - t0) * (i + 0.5) / n for i in range(n)]
    return [(t, frame_at(video, t)) for t in times]


def fmt(t: float) -> str:
    """Format seconds as m:ss."""
    return f"{int(t // 60)}:{int(t % 60):02d}"


async def analyse(client: LLMClient, video: Path, t0: float, t1: float, n: int = 6) -> dict[str, Any]:
    """Run one StretchAnalyst call and report validity, latency and tokens.

    :param client: vision client.
    :param video: source video.
    :param t0: stretch start.
    :param t1: stretch end.
    :param n: frames to send.
    :return: a report dict.
    """
    frames = frames_between(video, t0, t1, n)
    stem = f"{video.stem}_{int(t0)}"
    OUT.mkdir(parents=True, exist_ok=True)
    for i, (_, jpg) in enumerate(frames):
        (OUT / f"{stem}_{i}.jpg").write_bytes(jpg)
    text = f"Stretch {fmt(t0)}-{fmt(t1)}. {n} frames in time order. Transcript: not available."
    messages = [
        {"role": "system", "content": with_schema(STRETCH_ANALYST, StretchAnalysis)},
        user_message(text, [f for _, f in frames], client.endpoint.image_detail),
    ]
    res = await client.chat("smoke_stretch", messages)
    report: dict[str, Any] = {
        "video": video.stem,
        "span": f"{fmt(t0)}-{fmt(t1)}",
        "ms": res.ms,
        "in_tok": res.prompt_tokens,
        "out_tok": res.completion_tokens,
    }
    try:
        report["analysis"] = StretchAnalysis.model_validate(json.loads(res.message.content)).model_dump(
            mode="json"
        )
        report["valid"] = True
    except (ValidationError, json.JSONDecodeError) as exc:
        report["valid"] = False
        report["raw"] = (res.message.content or "")[:300]
        report["error"] = str(exc)[:200]
    return report


async def image_limit(client: LLMClient, video: Path, t0: float, t1: float) -> dict[int, str]:
    """Probe how many images one call accepts.

    :param client: vision client.
    :param video: source video.
    :param t0: span start.
    :param t1: span end.
    :return: image count -> "ok" or the error text.
    """
    frames = [f for _, f in frames_between(video, t0, t1, 48)]
    results: dict[int, str] = {}
    for n in (12, 24, 48):
        msg = [
            user_message(
                'Reply with JSON {"count": <number of images you see>}.',
                frames[:n],
                "low",
            )
        ]
        try:
            res = await client.chat("smoke_limit", msg)
            results[n] = f"ok in_tok={res.prompt_tokens} said={res.message.content.strip()[:40]}"
        except Exception as exc:  # noqa: BLE001 - smoke test reports any failure
            results[n] = f"FAIL {str(exc)[:150]}"
    return results


async def boundary(client: LLMClient, video: Path, cut: float, before: dict, after: dict) -> dict[str, Any]:
    """Run one BoundaryJudge call around a time point.

    :param client: vision client.
    :param video: source video.
    :param cut: the candidate cut time.
    :param before: analysis of the stretch before.
    :param after: analysis of the stretch after.
    :return: a report dict.
    """
    imgs = [
        frame_at(video, cut - 2.0),
        frame_at(video, cut - 0.5),
        frame_at(video, cut + 0.5),
        frame_at(video, cut + 2.0),
    ]
    text = (
        f"Cut at {fmt(cut)}. Frames: 2 before, then 2 after.\n"
        f"Before summary: {before.get('summary')}\nAfter summary: {after.get('summary')}\nTranscript: not available."
    )
    messages = [
        {"role": "system", "content": with_schema(BOUNDARY_JUDGE, BoundaryVerdict)},
        user_message(text, imgs, client.endpoint.image_detail),
    ]
    res = await client.chat("smoke_boundary", messages)
    report: dict[str, Any] = {
        "cut": fmt(cut),
        "ms": res.ms,
        "in_tok": res.prompt_tokens,
        "out_tok": res.completion_tokens,
    }
    try:
        report["verdict"] = BoundaryVerdict.model_validate(json.loads(res.message.content)).model_dump()
        report["valid"] = True
    except (ValidationError, json.JSONDecodeError) as exc:
        report["valid"] = False
        report["raw"] = (res.message.content or "")[:300]
        report["error"] = str(exc)[:200]
    return report


async def tool_loop(client: LLMClient, video: Path, t0: float, t1: float) -> dict[str, Any]:
    """Test tools + images + JSON mode in one conversation, frames returned in a user message.

    :param client: vision client.
    :param video: source video.
    :param t0: stretch start.
    :param t1: stretch end.
    :return: a report dict of what worked.
    """
    frames = [f for _, f in frames_between(video, t0, t1, 4)]
    system = with_schema(STRETCH_ANALYST, StretchAnalysis) + (
        "\n\nYou have a tool look_closer(t0, t1, n). For this test you MUST call it once, "
        "on any sub-range of the stretch, before giving your final JSON answer."
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        user_message(
            f"Stretch {t0:.0f}s-{t1:.0f}s (seconds). 4 frames. Transcript: not available.",
            frames,
            "low",
        ),
    ]
    report: dict[str, Any] = {"rounds": []}
    for round_no in range(3):
        res = await client.chat("smoke_loop", messages, tools=[LOOK_CLOSER], json_mode=True)
        msg = res.message
        calls = msg.tool_calls or []
        report["rounds"].append(
            {
                "ms": res.ms,
                "tool_calls": [c.function.name for c in calls],
                "in_tok": res.prompt_tokens,
            }
        )
        if not calls:
            try:
                StretchAnalysis.model_validate(json.loads(msg.content))
                report["final_json_valid"] = True
            except (ValidationError, json.JSONDecodeError) as exc:
                report["final_json_valid"] = False
                report["raw"] = (msg.content or "")[:300]
                report["error"] = str(exc)[:200]
            return report
        messages.append(msg.model_dump(exclude_none=True))
        extra: list[bytes] = []
        for call in calls:
            args = json.loads(call.function.arguments)
            n = max(1, min(int(args.get("n", 3)), 6))
            extra = [f for _, f in frames_between(video, float(args["t0"]), float(args["t1"]), n)]
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": f"{n} frames follow in the next user message.",
                }
            )
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Frames from look_closer:"},
                    *[image_part(f, "high") for f in extra],
                ],
            }
        )
    report["final_json_valid"] = False
    report["error"] = "no final answer within 3 rounds"
    return report


async def main() -> None:
    """Run the whole smoke test and print a JSON report."""
    parser = argparse.ArgumentParser()
    parser.add_argument("videos", nargs="+", type=Path)
    parser.add_argument("--seed", type=int, default=26)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    vision, text = make_clients(get_settings())

    plan: list[tuple[Path, float, float]] = []
    for i, video in enumerate(args.videos):
        dur = duration(video)
        n = 3 if i == 0 else 2
        for _ in range(n):
            length = rng.uniform(60, 180)
            start = rng.uniform(180, dur - 120 - length)
            plan.append((video, start, start + length))
    print(f"seed={args.seed} stretches:", [(v.stem, fmt(a), fmt(b)) for v, a, b in plan])

    reports = await asyncio.gather(*[analyse(vision, v, a, b) for v, a, b in plan])
    print("\n== StretchAnalyst (6 frames each) ==")
    for r in reports:
        print(json.dumps(r, ensure_ascii=False, indent=1))

    v0 = args.videos[0]
    dur0 = duration(v0)
    start = rng.uniform(300, dur0 - 400)
    mid = start + 90
    adj_a, adj_b = await asyncio.gather(analyse(vision, v0, start, mid), analyse(vision, v0, mid, mid + 90))
    print("\n== BoundaryJudge (2 before + 2 after, adjacent stretches) ==")
    print(
        json.dumps(
            await boundary(vision, v0, mid, adj_a.get("analysis", {}), adj_b.get("analysis", {})),
            ensure_ascii=False,
            indent=1,
        )
    )

    print("\n== Image count limit ==")
    print(json.dumps(await image_limit(vision, v0, start, start + 240), indent=1))

    print("\n== Agent loop: tools + images + JSON mode ==")
    try:
        print(json.dumps(await tool_loop(vision, v0, start, mid), ensure_ascii=False, indent=1))
    except Exception as exc:  # noqa: BLE001 - smoke test reports any failure
        print(f"TOOL LOOP FAILED: {type(exc).__name__}: {str(exc)[:400]}")

    print("\n== Text model ==")
    print("models:", await text.list_models())


if __name__ == "__main__":
    asyncio.run(main())
