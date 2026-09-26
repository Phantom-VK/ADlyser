import random

from adlyser.rules.safety import UNKNOWN_SCENE, add_sweep_tags, apply_sweep, blocking_tags, split_brands
from adlyser.schemas import Brand, SafetyTag, Scene, SweepResult

T = SafetyTag


def brand(bid, negatives=()):
    return Brand(
        id=bid,
        name=bid.title(),
        category="food",
        tagline="t",
        description="d",
        negative_tags=list(negatives),
        negative_contexts_raw=["raw"],
    )


def scene(tags=(), unknown=False, index=0):
    return Scene(
        index=index,
        start=0,
        end=10,
        stretch_indices=[0],
        summary="s",
        dominant_activity="talking",
        activity_tags=[],
        safety_tags=sorted(tags),
        unknown=unknown,
    )


FOOD = brand("food", [T.DEATH_GRIEF, T.FUNERAL_RITUAL, T.MEDICAL_ILLNESS])


def test_a_tag_on_the_scene_before_blocks_the_brand():
    assert blocking_tags(FOOD, scene({T.DEATH_GRIEF}), scene()) == ["death_grief"]


def test_a_tag_on_the_scene_after_blocks_the_brand():
    assert blocking_tags(FOOD, scene(), scene({T.MEDICAL_ILLNESS})) == ["medical_illness"]


def test_funeral_before_and_a_neutral_doorway_after_still_blocks():
    assert blocking_tags(FOOD, scene({T.FUNERAL_RITUAL}), scene(index=1)) == ["funeral_ritual"]


def test_all_blocking_tags_are_reported_sorted():
    found = blocking_tags(FOOD, scene({T.MEDICAL_ILLNESS}), scene({T.DEATH_GRIEF, T.VIOLENCE}))
    assert found == ["death_grief", "medical_illness"]


def test_no_overlap_means_eligible():
    assert blocking_tags(FOOD, scene({T.ALCOHOL}), scene({T.VIOLENCE})) == []


def test_a_brand_with_no_negative_tags_is_eligible_when_the_scenes_are_known():
    assert blocking_tags(brand("plain"), scene({T.DEATH_GRIEF}), scene({T.VIOLENCE})) == []


def test_an_unknown_scene_on_either_side_blocks_every_brand():
    for before, after in [(scene(unknown=True), scene()), (scene(), scene(unknown=True))]:
        assert blocking_tags(brand("plain"), before, after) == [UNKNOWN_SCENE]
        eligible, blocked = split_brands([FOOD, brand("plain")], before, after)
        assert eligible == [] and [b.brand_id for b in blocked] == ["food", "plain"]
        assert all(b.tags == [UNKNOWN_SCENE] for b in blocked)


def test_split_brands_reports_the_blocking_tag():
    eligible, blocked = split_brands([FOOD, brand("plain")], scene({T.DEATH_GRIEF}), scene())
    assert [b.id for b in eligible] == ["plain"]
    assert [(b.brand_id, b.tags) for b in blocked] == [("food", ["death_grief"])]


def test_sweep_adds_tags_and_keeps_the_existing_ones():
    out = add_sweep_tags(scene({T.ALCOHOL}), [T.DEATH_GRIEF])
    assert set(out.safety_tags) == {T.ALCOHOL, T.DEATH_GRIEF}


def test_sweep_tags_are_never_removed():
    rng = random.Random(3)
    tags = list(SafetyTag)
    for _ in range(100):
        start = set(rng.sample(tags, rng.randint(0, 6)))
        found = rng.sample(tags, rng.randint(0, 6))
        out = add_sweep_tags(scene(start), found)
        assert start <= set(out.safety_tags)
        assert set(out.safety_tags) == start | set(found)


def test_sweep_does_not_mutate_or_clear_unknown():
    original = scene({T.ALCOHOL}, unknown=True)
    out = add_sweep_tags(original, [T.VIOLENCE])
    assert out.unknown and original.safety_tags == [T.ALCOHOL]


def test_a_sweep_that_adds_death_grief_turns_an_eligible_food_brand_into_a_blocked_one():
    before, after = scene({T.ALCOHOL}), scene()
    assert [b.id for b in split_brands([FOOD], before, after)[0]] == ["food"]
    swept = add_sweep_tags(before, [T.DEATH_GRIEF])
    eligible, blocked = split_brands([FOOD], swept, after)
    assert eligible == [] and blocked[0].tags == ["death_grief"]


def sweep(tags=(), confidence=0.9):
    return SweepResult(safety_tags=list(tags), evidence="e", confidence=confidence)


def test_apply_sweep_adds_tags_and_keeps_a_confident_scene_known():
    out = apply_sweep(scene({T.ALCOHOL}), sweep([T.DEATH_GRIEF]), 0.5)
    assert set(out.safety_tags) == {T.ALCOHOL, T.DEATH_GRIEF} and not out.unknown


def test_an_unsure_or_failed_sweep_makes_the_scene_unknown_and_blocks_every_brand():
    assert apply_sweep(scene(), sweep(confidence=0.49), 0.5).unknown
    assert apply_sweep(scene(), sweep(confidence=0.0), 0.5).unknown
    swept = apply_sweep(scene(), sweep(confidence=0.0), 0.5)
    assert blocking_tags(brand("plain"), swept, scene()) == [UNKNOWN_SCENE]


def test_a_sweep_never_makes_an_unknown_scene_known():
    assert apply_sweep(scene(unknown=True), sweep([]), 0.5).unknown
