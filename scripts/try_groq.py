"""One-off check of Groq Whisper on a 4-minute Bengali stretch.

Run: ``uv run --env-file .env python -m scripts.try_groq``. Makes exactly two requests, one per model.
The key comes from ``GROQ_API_KEY`` in the environment and is never printed.
"""

import json
import os
import subprocess
import time
from pathlib import Path

from groq import Groq

VIDEO = Path("/home/vikramaditya/Downloads/hackathon_contents-20260926T060049Z-1-001/hackathon_contents/feluda.mp4")
START_S, END_S = 300, 540
MODELS = ("whisper-large-v3-turbo", "whisper-large-v3")
OUT = Path("data/groq_test")
SAMPLES = 5


def extract_flac(video: Path, start: float, end: float, out: Path) -> None:
    """Cut ``start``-``end`` seconds of ``video`` to mono 16 kHz flac."""
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(end - start), "-i", str(video)]
    subprocess.run([*cmd, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "flac", str(out)], check=True)


def bengali_share(text: str) -> float:
    """Fraction of the letters in ``text`` that are in the Bengali block (U+0980-U+09FF)."""
    letters = [c for c in text if c.isalpha()]
    return sum("ঀ" <= c <= "৿" for c in letters) / len(letters) if letters else 0.0


def clock(seconds: float) -> str:
    """Seconds as ``m:ss``."""
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


def main() -> None:
    """Transcribe the stretch with each model, save the raw JSON, print the summary."""
    if not os.environ.get("GROQ_API_KEY"):
        raise SystemExit("GROQ_API_KEY is not set (run with --env-file .env)")
    OUT.mkdir(parents=True, exist_ok=True)
    flac = OUT / "feluda_5-9.flac"
    extract_flac(VIDEO, START_S, END_S, flac)
    audio = flac.read_bytes()
    print(f"audio: {flac.name}, {len(audio) / 1e6:.2f} MB")
    client = Groq()
    for model in MODELS:
        began = time.monotonic()
        try:
            reply = client.audio.transcriptions.create(
                file=(flac.name, audio),
                model=model,
                temperature=0,
                response_format="verbose_json",
                language="bn",
            )
        except Exception as exc:  # noqa: BLE001 - report and move on to the next model
            print(f"\n{model}: FAILED {type(exc).__name__}: {str(exc)[:200]}")
            continue
        took = time.monotonic() - began
        data = reply.model_dump() if hasattr(reply, "model_dump") else dict(reply)
        (OUT / f"{model}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
        segs = data.get("segments") or []
        bengali = sum(bengali_share(s["text"]) > 0.5 for s in segs)
        print(f"\n{model}: {took:.1f} s, {len(segs)} segments, {bengali}/{len(segs)} mostly Bengali")
        step = max(len(segs) // SAMPLES, 1)
        for s in segs[::step][:SAMPLES]:
            print(f"  [{clock(START_S + s['start'])}-{clock(START_S + s['end'])}] {s['text'].strip()}")


if __name__ == "__main__":
    main()
