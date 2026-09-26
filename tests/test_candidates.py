import random
from itertools import pairwise

import pytest

from adlyser.config import CandidateConfig
from adlyser.rules.candidates import (
    break_window,
    find_candidates,
    silences_from_speech,
    skip_window,
    title_bounds,
)
from adlyser.schemas import Cut, SpeechSeg, Stretch, StretchAnalysis

CFG = CandidateConfig(
    min_silence_s=0.8,
    speech_guard_s=0.4,
    skip_start_s=180,
    skip_end_s=120,
    skip_start_fraction=1.0,  # the seconds apply as configured; SHORT scales them for short videos
    skip_end_fraction=1.0,
    min_spacing_s=20,
    max_candidates=60,
    allow_long_silence_without_cut=False,
    long_silence_s=2.0,
    titles_scan_fraction=0.25,
    titles_max_s=480,
)
DUR = 1000.0
SHORT = CFG.model_copy(update={"skip_start_fraction": 0.15, "skip_end_fraction": 0.1})


def cfg(**kw):
    return CFG.model_copy(update=kw)


def sp(a, b):
    return SpeechSeg(start=a, end=b)


def hard(t):
    return Cut(t=t, kind="hard")


def times(result):
    return [c.t for c in result.candidates]


# ---- silences_from_speech -------------------------------------------------


def test_silences_are_the_gaps_between_speech():
    assert silences_from_speech([sp(10, 20), sp(30, 40)], 50) == [(0, 10), (20, 30), (40, 50)]


def test_silences_merge_overlapping_and_unsorted_speech():
    assert silences_from_speech([sp(30, 40), sp(10, 25), sp(20, 32)], 50) == [(0, 10), (40, 50)]


def test_no_speech_means_one_silence_over_the_whole_video():
    assert silences_from_speech([], 50) == [(0, 50)]


# ---- the silence rule -------------------------------------------------------


def test_cut_inside_long_silence_is_a_candidate_at_the_cut():
    r = find_candidates([sp(0, 300), sp(310, 900)], [hard(305)], DUR, CFG)
    assert times(r) == [305]
    assert r.candidates[0].kind == "hard"


def test_silence_shorter_than_minimum_is_rejected():
    r = find_candidates([sp(0, 300), sp(300.7, 900)], [hard(300.35)], DUR, CFG)
    assert times(r) == []


def test_cut_closer_than_guard_to_speech_is_rejected():
    # silence 300..310; cut at 300.39 is 0.39 s after speech ends -> too close
    r = find_candidates([sp(0, 300), sp(310, 900)], [hard(300.39)], DUR, CFG)
    assert times(r) == []
    r = find_candidates([sp(0, 300), sp(310, 900)], [hard(309.61)], DUR, CFG)
    assert times(r) == []


def test_cut_exactly_at_guard_distance_is_allowed():
    r = find_candidates([sp(0, 300), sp(310, 900)], [hard(300.4)], DUR, CFG)
    assert times(r) == [300.4]


def test_cut_during_speech_is_rejected():
    r = find_candidates([sp(0, 900)], [hard(500)], DUR, CFG)
    assert times(r) == []


def test_silence_without_a_cut_is_rejected_by_default():
    r = find_candidates([sp(0, 300), sp(310, 900)], [], DUR, CFG)
    assert times(r) == []


def test_every_cut_inside_a_silence_is_a_candidate_before_thinning():
    speech = [sp(0, 300), sp(310, 900)]
    r = find_candidates(speech, [hard(301), hard(304.8), hard(309)], DUR, cfg(min_spacing_s=1))
    assert times(r) == [301, 304.8, 309]


def test_ranking_prefers_black_over_hard_then_earlier_time():
    speech = [sp(0, 300), sp(310, 900)]
    assert times(find_candidates(speech, [hard(310 - 0.5), Cut(t=302, kind="black")], DUR, CFG)) == [302]
    assert times(find_candidates(speech, [hard(303), hard(305)], DUR, CFG)) == [303]


def test_long_silence_with_regular_cuts_yields_many_candidates():
    speech = [sp(0, 250), sp(550, 1000)]  # a 5-minute silence
    cuts = [hard(260 + 30 * i) for i in range(10)]  # 260 .. 530
    r = find_candidates(speech, cuts, DUR, CFG)
    assert times(r) == [c.t for c in cuts]
    assert {c.silence_s for c in r.candidates} == {300}


def test_black_frame_counts_as_a_cut():
    r = find_candidates([sp(0, 300), sp(310, 900)], [Cut(t=305, kind="black")], DUR, CFG)
    assert r.candidates[0].kind == "black"


# ---- pre-planned relaxation --------------------------------------------------


def test_relaxation_admits_long_silence_without_cut_at_its_middle():
    c = cfg(allow_long_silence_without_cut=True)
    r = find_candidates([sp(0, 300), sp(310, 900)], [], DUR, c)
    assert times(r) == [305]
    assert r.candidates[0].kind == "silence"


def test_relaxation_does_not_admit_silences_shorter_than_long_silence():
    c = cfg(allow_long_silence_without_cut=True)
    r = find_candidates([sp(0, 300), sp(301.5, 900)], [], DUR, c)
    assert times(r) == []


def test_relaxation_prefers_a_real_cut_over_the_middle():
    c = cfg(allow_long_silence_without_cut=True)
    r = find_candidates([sp(0, 300), sp(310, 900)], [hard(302)], DUR, c)
    assert times(r) == [302] and r.candidates[0].kind == "hard"


# ---- windows ---------------------------------------------------------------------


def test_nothing_in_the_first_or_last_minutes():
    speech = [sp(0, 100), sp(110, 990), sp(999, 1000)]
    r = find_candidates(speech, [hard(105)], DUR, CFG)  # inside the first 180 s
    assert times(r) == []
    speech = [sp(0, 890), sp(900, 1000)]
    r = find_candidates(speech, [hard(895)], DUR, CFG)  # inside the last 120 s
    assert times(r) == []


def test_video_shorter_than_both_windows_gives_no_candidates():
    r = find_candidates([sp(0, 100), sp(110, 200)], [hard(105)], 250, CFG)
    assert times(r) == []


# ---- spacing and cap --------------------------------------------------------------


def test_close_candidates_keep_the_one_with_the_longer_silence():
    speech = [sp(0, 300), sp(310, 315), sp(318, 900)]  # silences 300-310 (10 s) and 315-318 (3 s)
    r = find_candidates(speech, [hard(305), hard(316.5)], DUR, CFG)
    assert times(r) == [305]


def test_candidates_at_least_spacing_apart_are_all_kept():
    speech = [sp(0, 300), sp(302, 400), sp(402, 900)]
    r = find_candidates(speech, [hard(301), hard(401)], DUR, CFG)
    assert times(r) == [301, 401]


def test_cap_keeps_the_longest_silences_in_time_order():
    speech, cuts, t = [], [], 200.0
    for i in range(10):
        gap = 1.0 + i * 0.5
        speech.append(sp(t, t + 30))
        cuts.append(hard(t + 30 + gap / 2))
        t += 30 + gap
    speech.append(sp(t, 990))
    r = find_candidates(speech, cuts, DUR, cfg(max_candidates=3))
    assert len(r.candidates) == 3
    assert times(r) == sorted(times(r))
    assert sorted(c.silence_s for c in r.candidates) == pytest.approx([4.5, 5.0, 5.5])


# ---- empty and degenerate inputs -------------------------------------------------


def test_no_cuts_and_no_speech_gives_nothing():
    assert times(find_candidates([], [], DUR, CFG)) == []


def test_fully_silent_video_keeps_cuts_that_are_spaced_apart():
    r = find_candidates([], [hard(400), hard(410), hard(500)], DUR, CFG)
    assert times(r) == [400, 500]


def test_funnel_counts_each_filter():
    speech = [sp(0, 300), sp(310, 400), sp(400.5, 900)]  # silences: 300-310 long, 400-400.5 short
    r = find_candidates(speech, [hard(305), hard(400.25)], DUR, CFG)
    f = r.funnel
    assert (f.silences, f.long_enough, f.with_cut, f.in_window, f.after_spacing_cap) == (3, 2, 1, 1, 1)


# ---- property: never within the guard of speech -----------------------------------


@pytest.mark.parametrize("seed", range(20))
def test_property_no_candidate_is_within_guard_of_speech(seed):
    rng = random.Random(seed)
    speech, t = [], 0.0
    while t < DUR:
        a = t + rng.uniform(0.05, 6)
        b = a + rng.uniform(0.2, 25)
        speech.append(sp(a, b))
        t = b
    cuts = [Cut(t=rng.uniform(0, DUR), kind=rng.choice(["hard", "black"])) for _ in range(400)]
    r = find_candidates(speech, cuts, DUR, cfg(allow_long_silence_without_cut=rng.random() < 0.5))
    g = CFG.speech_guard_s
    assert len(r.candidates) <= CFG.max_candidates
    cut_times = {c.t for c in cuts}
    for c in r.candidates:
        assert c.kind == "silence" or c.t in cut_times
        assert CFG.skip_start_s <= c.t <= DUR - CFG.skip_end_s
        assert c.silence_s >= CFG.min_silence_s
        for s in speech:
            assert s.end <= c.t - g + 1e-9 or s.start >= c.t + g - 1e-9
    ts = times(r)
    assert all(b - a >= CFG.min_spacing_s for a, b in pairwise(ts))


# ---- skip window scales down for short videos ---------------------------------------------------


def test_skip_window_is_the_configured_seconds_for_a_long_video_and_a_fraction_for_a_short_one():
    assert skip_window(3600, SHORT) == (180, 120)
    assert skip_window(120, SHORT) == (pytest.approx(18), pytest.approx(12))


def test_a_two_minute_video_can_have_a_candidate_inside_its_scaled_window():
    result = find_candidates([sp(0, 58), sp(63, 120)], [hard(60.5)], 120.0, SHORT)
    assert times(result) == [60.5]


def test_the_scaled_window_still_excludes_the_first_and_last_fractions():
    speech = [sp(0, 5), sp(8, 55), sp(59, 109), sp(113, 120)]
    result = find_candidates(speech, [hard(6.5), hard(57), hard(111)], 120.0, SHORT)
    assert times(result) == [57]  # 6.5 is inside the first 18 s, 111 inside the last 12 s


# ---- intro-aware window ----------------------------------------------------


def stretches(*edges, titles=()):
    """Consecutive stretches between the edges, and analyses that mark the listed indices as titles."""
    spans = [Stretch(index=i, start=a, end=b) for i, (a, b) in enumerate(pairwise(edges))]
    notes = [
        StretchAnalysis(
            summary="s", dominant_activity="a", setting="x", mood="m", confidence=0.9, is_titles=i in titles
        )
        for i in range(len(spans))
    ]
    return spans, notes


def test_without_titles_the_window_is_the_plain_skip_window():
    spans, notes = stretches(0, 250, 500, 750, 1000)
    intro_end, outro_start = title_bounds(spans, notes, DUR, SHORT)
    assert (intro_end, outro_start) == (0.0, None)
    assert break_window(DUR, SHORT, intro_end, outro_start) == (150.0, 900.0)
    assert break_window(DUR, SHORT) == (150.0, 900.0)


def test_a_titles_stretch_at_the_start_pushes_the_earliest_break():
    spans, notes = stretches(0, 100, 200, 500, 1000, titles={0, 1})
    intro_end, _ = title_bounds(spans, notes, DUR, SHORT)
    assert intro_end == 200
    assert break_window(DUR, SHORT, intro_end, None)[0] == 200 + 150


def test_a_titles_stretch_at_the_end_pulls_the_latest_break_back():
    spans, notes = stretches(0, 300, 600, 850, 1000, titles={3})
    _, outro_start = title_bounds(spans, notes, DUR, SHORT)
    assert outro_start == 850
    assert break_window(DUR, SHORT, 0.0, outro_start)[1] == 850 - 100


def test_titles_in_the_middle_of_the_episode_are_ignored():
    spans, notes = stretches(0, 300, 600, 700, 1000, titles={1, 2})
    assert title_bounds(spans, notes, DUR, SHORT) == (0.0, None)


def test_the_intro_is_capped_and_the_scan_scales_with_the_video():
    spans, notes = stretches(0, 900, 1000, titles={0})
    assert title_bounds(spans, notes, 4000.0, SHORT)[0] == 480  # capped at titles_max_s
    short = stretches(0, 30, 80, 400, titles={0, 1})
    assert title_bounds(*short, 400.0, SHORT) == (80, None)  # scan = 25% of 400 = 100 s
    assert (
        title_bounds(*stretches(0, 150, 400, titles={1}), 400.0, SHORT)[0] == 0.0
    )  # starts after the 100 s scan


def test_the_shipped_titles_settings_are_a_fraction_and_a_cap():
    from adlyser.config import get_settings

    cfg = get_settings().candidates
    assert 0 < cfg.titles_scan_fraction <= 0.5 and cfg.titles_max_s > 0
