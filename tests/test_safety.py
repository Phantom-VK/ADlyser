import random

from adlyser.rules.safety import UNKNOWN_SCENE, add_sweep_tags, apply_sweep, blocking_tags, split_brands
from adlyser.schemas import Brand, SafetyTag, Scene, SweepRecord

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


def sweep(tags=(), unsure=(), ok=True, full=True):
    return SweepRecord(
        safety_tags=list(tags), unsure_tags=list(unsure), evidence="e", ok=ok, full_coverage=full, frames=10
    )


def test_apply_sweep_adds_seen_tags_and_keeps_the_existing_ones():
    out = apply_sweep(scene({T.ALCOHOL}), sweep([T.DEATH_GRIEF]))
    assert set(out.safety_tags) == {T.ALCOHOL, T.DEATH_GRIEF}


def test_an_unsure_tag_counts_as_present_and_blocks_the_matching_brand():
    swept = apply_sweep(scene(), sweep(unsure=[T.DEATH_GRIEF]))
    assert T.DEATH_GRIEF in swept.safety_tags
    assert blocking_tags(FOOD, swept, scene()) == ["death_grief"]


def test_a_failed_sweep_keeps_unknown_as_it_was():
    assert apply_sweep(scene(unknown=True), sweep(ok=False)).unknown
    assert not apply_sweep(scene(unknown=False), sweep(ok=False)).unknown


def test_a_capped_sweep_keeps_unknown_as_it_was():
    assert apply_sweep(scene(unknown=True), sweep(full=False)).unknown


def test_a_full_coverage_sweep_clears_unknown():
    out = apply_sweep(scene(unknown=True), sweep([T.ALCOHOL]))
    assert not out.unknown and out.safety_tags == [T.ALCOHOL]


def test_a_full_coverage_sweep_that_finds_death_grief_clears_unknown_but_still_blocks_the_food_brand():
    out = apply_sweep(scene(unknown=True), sweep([T.DEATH_GRIEF]))
    assert not out.unknown and blocking_tags(FOOD, out, scene()) == ["death_grief"]


def test_sweep_never_removes_tags_whatever_the_outcome():
    rng = random.Random(5)
    tags = list(SafetyTag)
    for _ in range(100):
        start = set(rng.sample(tags, rng.randint(0, 6)))
        rec = sweep(
            rng.sample(tags, rng.randint(0, 4)),
            rng.sample(tags, rng.randint(0, 3)),
            rng.random() < 0.7,
            rng.random() < 0.5,
        )
        out = apply_sweep(scene(start, unknown=rng.random() < 0.5), rec)
        assert start <= set(out.safety_tags)
