"""Stretches between candidate pauses, and scenes built by merging them. Pure functions."""

from collections import defaultdict
from itertools import pairwise

from adlyser.errors import AdlyserError
from adlyser.schemas import Candidate, SafetyTag, Scene, Stretch, StretchAnalysis


def make_stretches(candidates: list[Candidate], duration_s: float) -> list[Stretch]:
    """Cut the video at every candidate: the stretches are what the StretchAnalyst looks at.

    :param candidates: candidate pauses in time order.
    :param duration_s: video length in seconds.
    :return: consecutive stretches that cover ``[0, duration_s]``.
    """
    edges = [0.0, *(c.t for c in candidates), duration_s]
    return [Stretch(index=i, start=a, end=b) for i, (a, b) in enumerate(pairwise(edges))]


def _merge(index: int, group: list[tuple[Stretch, StretchAnalysis]], min_confidence: float) -> Scene:
    """Merge consecutive stretches into one scene: union of tags, duration-weighted activity."""
    weight: defaultdict[str, float] = defaultdict(float)
    activity_tags: list[str] = []
    safety: set[SafetyTag] = set()
    for stretch, analysis in group:
        weight[analysis.dominant_activity] += stretch.end - stretch.start
        activity_tags += [t for t in analysis.activity_tags if t not in activity_tags]
        safety |= set(analysis.safety_tags)
    return Scene(
        index=index,
        start=group[0][0].start,
        end=group[-1][0].end,
        stretch_indices=[s.index for s, _ in group],
        summary=" ".join(a.summary for _, a in group),
        dominant_activity=max(weight, key=lambda k: weight[k]),
        activity_tags=activity_tags,
        safety_tags=sorted(safety),
        unknown=any(a.confidence < min_confidence for _, a in group),
    )


def build_scenes(
    stretches: list[Stretch],
    analyses: list[StretchAnalysis],
    scene_changes: list[bool],
    min_confidence: float,
) -> list[Scene]:
    """Merge stretches across candidates that are not scene changes.

    A scene's safety tags are the UNION of its stretches' tags. A scene is ``unknown``
    (blocked for every brand) if any of its stretches has a failed or low-confidence analysis.

    :param stretches: consecutive stretches.
    :param analyses: one analysis per stretch (a failed call is an analysis with confidence 0).
    :param scene_changes: one flag per candidate between stretches, true if it is a real scene change.
    :param min_confidence: analyses below this confidence make their scene unknown.
    :return: scenes in time order.
    :raises AdlyserError: if the input lengths do not line up.
    """
    if len(analyses) != len(stretches) or len(scene_changes) != len(stretches) - 1:
        raise AdlyserError(
            f"need one analysis per stretch and one flag per candidate, got {len(stretches)} stretches, "
            f"{len(analyses)} analyses, {len(scene_changes)} flags"
        )
    scenes: list[Scene] = []
    group: list[tuple[Stretch, StretchAnalysis]] = []
    for i, pair in enumerate(zip(stretches, analyses, strict=True)):
        group.append(pair)
        if i == len(stretches) - 1 or scene_changes[i]:
            scenes.append(_merge(len(scenes), group, min_confidence))
            group = []
    return scenes
