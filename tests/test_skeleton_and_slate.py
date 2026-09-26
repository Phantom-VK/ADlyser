from itertools import pairwise
from pathlib import Path

from adlyser.config import CreativesConfig, PacingConfig
from adlyser.emit.creatives import slate_command
from adlyser.schemas import Candidate, Creative
from adlyser.skeleton import pick_breaks, to_specs

PACING = PacingConfig(max_breaks_per_hour=6, min_gap_s=300, ad_duration_s=30, max_ad_load_pct=12)


def cand(t, silence):
    return Candidate(t=t, silence_start=t - silence / 2, silence_end=t + silence / 2, kind="hard")


def test_picks_longest_silences_at_least_min_gap_apart_up_to_the_hourly_cap():
    cands = [cand(400, 5), cand(500, 9), cand(900, 3), cand(1300, 7)]
    chosen = pick_breaks(cands, 1800, PACING)  # 30 min -> at most 3 breaks
    assert [c.t for c in chosen] == [500, 900, 1300]
    assert all(b.t - a.t >= 300 for a, b in pairwise(chosen))


def test_short_video_gets_no_breaks_when_the_cap_rounds_to_zero():
    assert pick_breaks([cand(400, 5)], 300, PACING) == []


def test_no_candidates_gives_no_breaks():
    assert pick_breaks([], 1800, PACING) == []


def test_specs_have_sequential_ids():
    creative = Creative(ad_id="promo", title="p", duration_s=10, media_url="/x.mp4")
    specs = to_specs([cand(400, 5), cand(900, 5)], creative)
    assert [s.break_id for s in specs] == ["break-1", "break-2"]


def test_slate_command_reads_text_from_files_and_uses_configured_size_and_duration():
    cfg = CreativesConfig(
        duration_s=10, width=960, height=540, font="DejaVu Sans", promo_title="t", promo_subtitle="s"
    )
    cmd = slate_command(Path("/t/title.txt"), Path("/t/sub.txt"), Path("/o/out.mp4"), cfg)
    joined = " ".join(cmd)
    assert "textfile=/t/title.txt" in joined and "textfile=/t/sub.txt" in joined
    assert "s=960x540:d=10" in joined and cmd[-1] == "/o/out.mp4"
