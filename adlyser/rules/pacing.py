"""Pacing solver: choose breaks from confirmed scene changes under hard constraints. Pure functions."""

from adlyser.config import PacingConfig
from adlyser.schemas import BreakOption


def max_breaks(duration_s: float, cfg: PacingConfig) -> int:
    """Most breaks allowed by the hourly rate and by the ad-load cap.

    A video at least ``min_duration_for_break_s`` long may always have one break, even when the two
    caps round down to zero (a 2-minute upload still gets a break).

    :param duration_s: video length in seconds.
    :param cfg: pacing settings.
    :return: the largest allowed break count.
    """
    by_rate = int(cfg.max_breaks_per_hour * duration_s / 3600)
    by_load = int(cfg.max_ad_load_pct / 100 * duration_s / cfg.ad_duration_s)
    limit = max(0, min(by_rate, by_load))
    return max(limit, 1) if duration_s >= cfg.min_duration_for_break_s else limit


def _best(pool: list[BreakOption], limit: int, cfg: PacingConfig) -> list[BreakOption]:
    """Highest total score using at most ``limit`` options at least ``min_gap_s`` apart (``pool`` in time order)."""
    n = len(pool)
    # best[k][i]: top score using k+1 breaks with the last one at pool[i]; None if impossible.
    best: list[list[float | None]] = [[o.break_score for o in pool]]
    prev: list[list[int | None]] = [[None] * n]
    for k in range(1, limit):
        row: list[float | None] = [None] * n
        back: list[int | None] = [None] * n
        for i in range(n):
            for j in range(i):
                before = best[k - 1][j]
                if before is None or pool[i].candidate.t - pool[j].candidate.t < cfg.min_gap_s:
                    continue
                total = before + pool[i].break_score
                if row[i] is None or total > row[i]:
                    row[i], back[i] = total, j
        best.append(row)
        prev.append(back)
    top: tuple[float, int, int] | None = None
    for k, row in enumerate(best):
        for i, score in enumerate(row):
            if score is not None and (top is None or score > top[0]):
                top = (score, k, i)
    assert top is not None
    _, k, i = top
    chosen: list[BreakOption] = []
    cursor: int | None = i
    while cursor is not None:
        chosen.append(pool[cursor])
        cursor = prev[k][cursor]
        k -= 1
    return chosen[::-1]


def select_breaks(
    options: list[BreakOption],
    duration_s: float,
    cfg: PacingConfig,
    pinned: list[BreakOption] | None = None,
) -> list[BreakOption]:
    """Pick the breaks with the highest total score subject to the pacing constraints.

    Dynamic programming over options in time order. Options below ``min_break_score`` are never used;
    chosen breaks are at least ``min_gap_s`` apart and no more than ``max_breaks`` in number.
    ``pinned`` breaks (already approved) are always kept: they count against the cap, and new breaks
    keep the minimum gap from them.

    :param options: confirmed scene changes with their break scores, any order.
    :param duration_s: video length in seconds.
    :param cfg: pacing settings.
    :param pinned: breaks that must stay, whatever their score.
    :return: the pinned and the newly chosen options in time order.
    """
    pinned = pinned or []
    fixed = [o.candidate.t for o in pinned]
    pool = sorted(
        (
            o
            for o in options
            if o.break_score >= cfg.min_break_score
            and o.candidate.t not in fixed
            and all(abs(o.candidate.t - t) >= cfg.min_gap_s for t in fixed)
        ),
        key=lambda o: o.candidate.t,
    )
    limit = min(max_breaks(duration_s, cfg) - len(pinned), len(pool))
    chosen = _best(pool, limit, cfg) if limit > 0 else []
    return sorted([*pinned, *chosen], key=lambda o: o.candidate.t)


def can_add(times: list[float], t: float, duration_s: float, cfg: PacingConfig) -> bool:
    """Whether one more break at ``t`` keeps the pacing constraints, given the breaks already placed.

    :param times: times of the breaks already placed.
    :param t: the time of the break to add.
    :param duration_s: video length in seconds.
    :param cfg: pacing settings.
    :return: true if the count cap and the minimum gap both hold.
    """
    return len(times) < max_breaks(duration_s, cfg) and all(abs(t - x) >= cfg.min_gap_s for x in times)
