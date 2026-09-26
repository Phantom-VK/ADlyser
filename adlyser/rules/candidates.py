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


def _pick(silence: tuple[float, float], cuts: list[Cut], cfg: CandidateConfig) -> list[Candidate]:
    """Return every candidate inside one silence.

    Each cut at least ``speech_guard_s`` from both edges of the silence is a candidate, so no
    speech lies within the guard. A silence with no cut yields one mid-silence candidate only
    when the relaxation flag is on and the silence is long enough.
    """
    start, end = silence
    lo, hi = start + cfg.speech_guard_s - _EPS, end - cfg.speech_guard_s + _EPS
    inside = [
        Candidate(t=c.t, silence_start=start, silence_end=end, kind=c.kind) for c in cuts if lo <= c.t <= hi
    ]
    if inside:
        return inside
    if cfg.allow_long_silence_without_cut and end - start >= cfg.long_silence_s:
        return [Candidate(t=(start + end) / 2, silence_start=start, silence_end=end, kind="silence")]
    return []


def skip_window(duration: float, cfg: CandidateConfig) -> tuple[float, float]:
    """Seconds to skip at the start and at the end: the configured amount, or less for a short video.

    :param duration: video length in seconds.
    :param cfg: candidate rules from config.
    :return: ``(skip_start, skip_end)`` = ``min(configured, fraction x duration)``.
    """
    return (
        min(cfg.skip_start_s, cfg.skip_start_fraction * duration),
        min(cfg.skip_end_s, cfg.skip_end_fraction * duration),
    )


def _rank(cand: Candidate) -> tuple[float, int, float]:
    """Sort key: longer silence first, then black before hard, then earlier."""
    return (-cand.silence_s, 0 if cand.kind == "black" else 1, cand.t)


def find_candidates(
    speech: list[SpeechSeg], cuts: list[Cut], duration: float, cfg: CandidateConfig
) -> CandidateResult:
    """Find candidate ad-break pauses.

    A candidate is a cut (or fade to black) inside a silence of at least ``min_silence_s``,
    at least ``speech_guard_s`` away from any speech (a long silence can hold many), outside the first ``skip_start_s`` and last
    ``skip_end_s`` seconds (less for a short video, see ``skip_window``). Candidates are thinned to ``min_spacing_s`` (ranked by silence length, then black before hard, then time)
    and capped at ``max_candidates``.

    :param speech: detected speech spans.
    :param cuts: hard cuts and black-frame midpoints.
    :param duration: video length in seconds.
    :param cfg: candidate rules from config.
    :return: candidates in time order plus the funnel counts.
    """
    silences = silences_from_speech(speech, duration)
    long_enough = [s for s in silences if s[1] - s[0] >= cfg.min_silence_s - _EPS]
    picked = [c for s in long_enough for c in _pick(s, cuts, cfg)]
    skip_start, skip_end = skip_window(duration, cfg)
    in_window = [c for c in picked if skip_start <= c.t <= duration - skip_end]

    kept: list[Candidate] = []
    for cand in sorted(in_window, key=_rank):
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
