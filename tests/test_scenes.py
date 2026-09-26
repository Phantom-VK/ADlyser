from itertools import pairwise

import pytest

from adlyser.errors import AdlyserError
from adlyser.rules.scenes import build_scenes, make_stretches, scenes_around
from adlyser.schemas import Candidate, SafetyTag, Stretch, StretchAnalysis

MIN_CONF = 0.5


def cand(t):
    return Candidate(t=t, silence_start=t - 1, silence_end=t + 1, kind="hard")


def analysis(tags=(), activity="talking", confidence=0.9, summary="s"):
    return StretchAnalysis(
        summary=summary,
        dominant_activity=activity,
        activity_tags=[activity],
        setting="room",
        mood="calm",
        safety_tags=list(tags),
        confidence=confidence,
    )


def stretches(*bounds):
    return [Stretch(index=i, start=a, end=b) for i, (a, b) in enumerate(pairwise(bounds))]


# ---- make_stretches ---------------------------------------------------------


def test_stretches_cover_the_video_between_candidates():
    out = make_stretches([cand(300), cand(600)], 1000.0)
    assert [(s.start, s.end) for s in out] == [(0, 300), (300, 600), (600, 1000)]
    assert [s.index for s in out] == [0, 1, 2]


def test_no_candidates_is_one_stretch():
    assert [(s.start, s.end) for s in make_stretches([], 1000.0)] == [(0, 1000)]


# ---- build_scenes -----------------------------------------------------------


def test_scene_changes_split_scenes_at_the_candidate():
    st = stretches(0, 300, 600, 1000)
    scenes = build_scenes(st, [analysis()] * 3, [True, True], MIN_CONF)
    assert [(s.start, s.end) for s in scenes] == [(0, 300), (300, 600), (600, 1000)]


def test_non_changes_merge_stretches():
    st = stretches(0, 300, 600, 1000)
    scenes = build_scenes(st, [analysis()] * 3, [False, True], MIN_CONF)
    assert [(s.start, s.end, s.stretch_indices) for s in scenes] == [(0, 600, [0, 1]), (600, 1000, [2])]


def test_merged_scene_tags_are_the_union_of_its_stretches():
    st = stretches(0, 300, 600)
    scenes = build_scenes(
        st,
        [analysis({SafetyTag.FUNERAL_RITUAL}), analysis({SafetyTag.ALCOHOL, SafetyTag.FUNERAL_RITUAL})],
        [False],
        MIN_CONF,
    )
    assert len(scenes) == 1
    assert set(scenes[0].safety_tags) == {SafetyTag.FUNERAL_RITUAL, SafetyTag.ALCOHOL}


def test_funeral_then_neutral_doorway_in_one_scene_keeps_the_funeral_tag():
    st = stretches(0, 300, 600)
    scenes = build_scenes(st, [analysis({SafetyTag.FUNERAL_RITUAL}), analysis()], [False], MIN_CONF)
    assert SafetyTag.FUNERAL_RITUAL in scenes[0].safety_tags


def test_tags_do_not_leak_across_a_scene_change():
    st = stretches(0, 300, 600)
    scenes = build_scenes(st, [analysis({SafetyTag.VIOLENCE}), analysis()], [True], MIN_CONF)
    assert scenes[0].safety_tags == [SafetyTag.VIOLENCE]
    assert scenes[1].safety_tags == []


def test_failed_analysis_makes_the_scene_unknown():
    st = stretches(0, 300)
    scenes = build_scenes(st, [analysis(confidence=0.0)], [], MIN_CONF)
    assert scenes[0].unknown


def test_low_confidence_makes_the_scene_unknown():
    st = stretches(0, 300)
    assert build_scenes(st, [analysis(confidence=0.49)], [], MIN_CONF)[0].unknown
    assert not build_scenes(st, [analysis(confidence=0.5)], [], MIN_CONF)[0].unknown


def test_one_unknown_stretch_makes_the_merged_scene_unknown():
    st = stretches(0, 300, 600)
    scenes = build_scenes(st, [analysis(), analysis(confidence=0.1)], [False], MIN_CONF)
    assert scenes[0].unknown


def test_unknown_does_not_leak_across_a_scene_change():
    st = stretches(0, 300, 600)
    scenes = build_scenes(st, [analysis(confidence=0.1), analysis()], [True], MIN_CONF)
    assert [s.unknown for s in scenes] == [True, False]


def test_dominant_activity_is_duration_weighted():
    st = stretches(0, 100, 600)
    scenes = build_scenes(st, [analysis(activity="cooking"), analysis(activity="arguing")], [False], MIN_CONF)
    assert scenes[0].dominant_activity == "arguing"


def test_activity_tags_are_merged_without_duplicates():
    st = stretches(0, 100, 200)
    scenes = build_scenes(st, [analysis(activity="cooking"), analysis(activity="cooking")], [False], MIN_CONF)
    assert scenes[0].activity_tags == ["cooking"]


def test_scenes_are_numbered_and_contiguous():
    st = stretches(0, 300, 600, 1000)
    scenes = build_scenes(st, [analysis()] * 3, [True, False], MIN_CONF)
    assert [s.index for s in scenes] == [0, 1]
    assert scenes[0].end == scenes[1].start


def test_mismatched_inputs_raise():
    st = stretches(0, 300, 600)
    with pytest.raises(AdlyserError):
        build_scenes(st, [analysis()], [False], MIN_CONF)
    with pytest.raises(AdlyserError):
        build_scenes(st, [analysis()] * 2, [], MIN_CONF)


def test_scenes_around_a_confirmed_change():
    st = stretches(0, 300, 600, 1000)
    scenes = build_scenes(st, [analysis()] * 3, [True, True], MIN_CONF)
    assert scenes_around(scenes, 300) == (0, 1)
    assert scenes_around(scenes, 600) == (1, 2)


def test_scenes_around_a_non_boundary_raises():
    st = stretches(0, 300, 600)
    scenes = build_scenes(st, [analysis()] * 2, [False], MIN_CONF)
    with pytest.raises(AdlyserError):
        scenes_around(scenes, 300)
