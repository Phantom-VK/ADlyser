from pathlib import Path

from adlyser.config import CreativesConfig
from adlyser.emit import creatives
from adlyser.emit.creatives import make_slate, slate_command, slate_name

CFG = CreativesConfig(
    duration_s=10, width=960, height=540, font="DejaVu Sans", promo_title="t", promo_subtitle="s"
)


def test_slate_command_reads_text_from_files_and_uses_configured_size_and_duration():
    cmd = slate_command(Path("/t/title.txt"), Path("/t/sub.txt"), Path("/o/out.mp4"), CFG)
    joined = " ".join(cmd)
    assert "textfile=/t/title.txt" in joined and "textfile=/t/sub.txt" in joined
    assert "s=960x540:d=10" in joined and cmd[-1] == "/o/out.mp4"


def test_the_slate_name_carries_a_hash_of_the_title_and_subtitle():
    a = slate_name("grain-grove", "Grain & Grove", "Eat well")
    assert a == slate_name("grain-grove", "Grain & Grove", "Eat well")
    assert a.startswith("grain-grove-") and a.endswith(".mp4")
    assert a != slate_name("grain-grove", "Grain & Grove", "Eat better")  # a new tagline is a new file
    assert a != slate_name("grain-grove", "Grain and Grove", "Eat well")


def test_the_title_and_subtitle_are_not_ambiguous_in_the_hash():
    assert slate_name("x", "ab", "c") != slate_name("x", "a", "bc")


def test_temp_files_are_unique_per_call(tmp_path, monkeypatch):
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append(Path(cmd[-1]))
        Path(cmd[-1]).write_bytes(b"x")

    monkeypatch.setattr(creatives.subprocess, "run", fake_run)
    out = tmp_path / "a.mp4"
    make_slate("t", "s", out, CFG)
    make_slate("t", "s", out, CFG)
    assert seen[0] != seen[1] and all(p.suffix == ".tmp" and p != out for p in seen)
    assert out.exists() and not list(tmp_path.glob("*.tmp"))
