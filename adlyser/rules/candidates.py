"""Candidate pauses: cut points that sit inside real silence. Pure functions, no I/O, no LLM."""

from adlyser.config import CandidateConfig
from adlyser.schemas import Candidate, CandidateResult, Cut, Funnel, SpeechSeg

_EPS = 1e-9


def silences_from_speech(speech: list[SpeechSeg], duration: float) -> list[tuple[float, float]]:
    """Return the gaps between speech spans over ``[0, duration]``.

    :param speech: speech spans, in any order, possibly overlapping.
    :param duration: video length in seconds.
    :return: ``(start, end)`` silences in time order.
    """
    silences: list[tuple[float, float]] = []
    cursor = 0.0
    for seg in sorted(speech, key=lambda s: (s.start, s.end)):
        if seg.start > cursor:
            silences.append((cursor, min(seg.start, duration)))
        cursor = max(cursor, seg.end)
        if cursor >= duration:
            break
    if cursor < duration:
        silences.append((cursor, duration))
    return [(a, b) for a, b in silences if b > a]


def _pick(silence: tuple[float, float], cuts: list[Cut], cfg: CandidateConfig) -> Candidate | None:
    """Choose the cut point for one silence, or None if it has no safe one.

    The cut must be at least ``speech_guard_s`` from both edges of the silence, so no speech
    lies within the guard. Among several cuts, the one nearest the middle wins.
    """
    start, end = silence
    lo, hi = start + cfg.speech_guard_s - _EPS, end - cfg.speech_guard_s + _EPS
    inside = [c for c in cuts if lo <= c.t <= hi]
    middle = (start + end) / 2
    if inside:
        best = min(inside, key=lambda c: (abs(c.t - middle), c.t))
        return Candidate(t=best.t, silence_start=start, silence_end=end, kind=best.kind)
    if cfg.allow_long_silence_without_cut and end - start >= cfg.long_silence_s:
        return Candidate(t=middle, silence_start=start, silence_end=end, kind="silence")
    return None


def find_candidates(
    speech: list[SpeechSeg], cuts: list[Cut], duration: float, cfg: CandidateConfig
) -> CandidateResult:
    """Find candidate ad-break pauses.

    A candidate is a cut (or fade to black) inside a silence of at least ``min_silence_s``,
    at least ``speech_guard_s`` away from any speech, outside the first ``skip_start_s`` and last
    ``skip_end_s`` seconds. Candidates are thinned to ``min_spacing_s`` (longer silence wins)
    and capped at ``max_candidates``.

    :param speech: detected speech spans.
    :param cuts: hard cuts and black-frame midpoints.
    :param duration: video length in seconds.
    :param cfg: candidate rules from config.
    :return: candidates in time order plus the funnel counts.
    """
    silences = silences_from_speech(speech, duration)
    long_enough = [s for s in silences if s[1] - s[0] >= cfg.min_silence_s - _EPS]
    picked = [c for s in long_enough if (c := _pick(s, cuts, cfg)) is not None]
    in_window = [c for c in picked if cfg.skip_start_s <= c.t <= duration - cfg.skip_end_s]

    kept: list[Candidate] = []
    for cand in sorted(in_window, key=lambda c: (-c.silence_s, c.t)):
        if len(kept) >= cfg.max_candidates:
            break
        if all(abs(cand.t - k.t) >= cfg.min_spacing_s for k in kept):
            kept.append(cand)

    funnel = Funnel(
        silences=len(silences),
        long_enough=len(long_enough),
        with_cut=len(picked),
        in_window=len(in_window),
        after_spacing_cap=len(kept),
    )
    return CandidateResult(candidates=sorted(kept, key=lambda c: c.t), funnel=funnel)
