"""THROWAWAY walking skeleton: pick the longest-silence candidates and give every break the promo slate.

Replaced in Phase 2/3 by the BoundaryJudge, PacingSolver and BrandMatcher. Delete it then.
"""

from adlyser.config import PacingConfig
from adlyser.schemas import AdBreakSpec, Candidate, Creative


def pick_breaks(candidates: list[Candidate], duration_s: float, pacing: PacingConfig) -> list[Candidate]:
    """Take the longest silences, at least ``min_gap_s`` apart, up to the hourly cap.

    :param candidates: candidate pauses.
    :param duration_s: video length in seconds.
    :param pacing: pacing settings.
    :return: chosen candidates in time order.
    """
    max_breaks = int(pacing.max_breaks_per_hour * duration_s / 3600)
    chosen: list[Candidate] = []
    for cand in sorted(candidates, key=lambda c: (-c.silence_s, c.t)):
        if len(chosen) >= max_breaks:
            break
        if all(abs(cand.t - c.t) >= pacing.min_gap_s for c in chosen):
            chosen.append(cand)
    return sorted(chosen, key=lambda c: c.t)


def to_specs(chosen: list[Candidate], creative: Creative) -> list[AdBreakSpec]:
    """Give every chosen break the same creative.

    :param chosen: chosen candidates.
    :param creative: the creative to play.
    :return: break specs with sequential ids.
    """
    return [
        AdBreakSpec(break_id=f"break-{i}", time_s=c.t, creative=creative) for i, c in enumerate(chosen, 1)
    ]
