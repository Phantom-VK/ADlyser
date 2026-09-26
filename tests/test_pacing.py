import random
from itertools import combinations, pairwise

from adlyser.config import PacingConfig
from adlyser.rules.pacing import can_add, max_breaks, select_breaks
from adlyser.schemas import BreakOption, Candidate

CFG = PacingConfig(
    max_breaks_per_hour=6,
    min_gap_s=300,
    ad_duration_s=30,
    max_ad_load_pct=12,
    min_break_score=0.5,
    min_duration_for_break_s=90,
)


def opt(t, score):
    return BreakOption(
        candidate=Candidate(t=t, silence_start=t - 1, silence_end=t + 1, kind="hard"), break_score=score
    )


def times(chosen):
    return [o.candidate.t for o in chosen]


def cfg(**kw):
    return CFG.model_copy(update=kw)


def test_max_breaks_is_the_tighter_of_hourly_rate_and_ad_load():
    assert max_breaks(3600, CFG) == 6
    assert max_breaks(1800, CFG) == 3
    assert max_breaks(3600, cfg(max_ad_load_pct=1)) == 1  # 36 s of ads / 30 s each
    assert max_breaks(60, CFG) == 0


def test_nothing_to_choose():
    assert select_breaks([], 3600, CFG) == []


def test_picks_the_best_scores_when_the_cap_binds():
    options = [opt(400, 0.6), opt(800, 0.9), opt(1200, 0.7), opt(1600, 0.95)]
    chosen = select_breaks(options, 1800, cfg(max_breaks_per_hour=4))  # cap = 2 for 30 min
    assert times(chosen) == [800, 1600]


def test_min_gap_forces_a_trade_off():
    # 800 and 1000 are 200 s apart: only one of them can be used.
    options = [opt(800, 0.9), opt(1000, 0.8), opt(1500, 0.6)]
    chosen = select_breaks(options, 3600, CFG)
    assert times(chosen) == [800, 1500]


def test_prefers_two_good_breaks_over_one_slightly_better_blocker():
    options = [opt(500, 0.7), opt(700, 0.75), opt(900, 0.7)]
    chosen = select_breaks(options, 3600, cfg(min_gap_s=350))
    assert times(chosen) == [500, 900]


def test_breaks_below_the_minimum_score_are_never_chosen():
    options = [opt(500, 0.49), opt(1000, 0.5)]
    assert times(select_breaks(options, 3600, CFG)) == [1000]


def test_input_order_does_not_matter():
    options = [opt(1600, 0.95), opt(400, 0.6), opt(1200, 0.7), opt(800, 0.9)]
    a = select_breaks(options, 1800, cfg(max_breaks_per_hour=4))
    b = select_breaks(sorted(options, key=lambda o: o.candidate.t), 1800, cfg(max_breaks_per_hour=4))
    assert times(a) == times(b)


def brute_force(options, duration, c):
    """Best total score over every subset that meets the constraints."""
    eligible = sorted((o for o in options if o.break_score >= c.min_break_score), key=lambda o: o.candidate.t)
    best = 0.0
    for k in range(1, max_breaks(duration, c) + 1):
        for subset in combinations(eligible, k):
            if all(b.candidate.t - a.candidate.t >= c.min_gap_s for a, b in pairwise(subset)):
                best = max(best, sum(o.break_score for o in subset))
    return best


def test_property_constraints_hold_and_the_score_is_optimal():
    rng = random.Random(7)
    for _ in range(150):
        duration = rng.choice([900.0, 1800.0, 2400.0, 3600.0])
        c = cfg(min_gap_s=rng.choice([60, 200, 300]), max_breaks_per_hour=rng.choice([2, 4, 6, 10]))
        options = [opt(rng.uniform(180, duration - 120), rng.random()) for _ in range(rng.randint(0, 9))]
        chosen = select_breaks(options, duration, c)
        ts = times(chosen)
        assert ts == sorted(ts)
        assert len(chosen) <= max_breaks(duration, c)
        assert all(b - a >= c.min_gap_s for a, b in pairwise(ts))
        assert all(o.break_score >= c.min_break_score for o in chosen)
        assert abs(sum(o.break_score for o in chosen) - brute_force(options, duration, c)) < 1e-9


def test_can_add_respects_the_gap_and_the_cap():
    assert can_add([], 500, 3600, CFG)
    assert not can_add([400], 500, 3600, CFG)  # too close
    assert can_add([400], 800, 3600, CFG)
    assert can_add([400, 800], 1200, 1800, CFG)  # 30 min allows 3
    assert not can_add([400, 800, 1200], 1600, 1800, CFG)


# ---- short videos ---------------------------------------------------------------------------------


def test_a_video_at_least_min_duration_long_may_have_one_break_even_when_the_caps_round_to_zero():
    assert max_breaks(120, CFG) == 1  # the rate and the load cap both give 0
    assert max_breaks(89, CFG) == 0


def test_a_120_second_video_with_one_good_candidate_gets_one_break():
    assert times(select_breaks([opt(60, 0.8)], 120, CFG)) == [60]


def test_a_short_video_still_gets_only_one_break():
    assert times(select_breaks([opt(40, 0.7), opt(80, 0.9)], 120, cfg(min_gap_s=10))) == [80]


# ---- pinned breaks --------------------------------------------------------------------------------


def test_pinned_breaks_are_always_kept_and_count_against_the_cap():
    options = [opt(500, 0.6), opt(1000, 0.9), opt(1500, 0.95)]
    chosen = select_breaks(options, 1800, cfg(max_breaks_per_hour=4), pinned=[opt(500, 0.6)])  # cap 2
    assert times(chosen) == [500, 1500]


def test_pinned_breaks_keep_their_gap_against_new_ones():
    chosen = select_breaks([opt(600, 0.99), opt(1200, 0.5)], 3600, CFG, pinned=[opt(500, 0.6)])
    assert times(chosen) == [500, 1200]  # 600 is 100 s from the pinned break, min gap is 300


def test_a_pinned_break_below_the_score_floor_is_still_kept():
    assert times(select_breaks([], 3600, CFG, pinned=[opt(500, 0.1)])) == [500]
