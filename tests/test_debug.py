from adlyser.emit.debug import build_debug
from adlyser.schemas import Blocked as BlockedModel
from adlyser.schemas import (
    BoundaryVerdict,
    Brand,
    BrandChoice,
    BreakPlan,
    Candidate,
    Funnel,
    SafetyTag,
    Scene,
    ShortlistEntry,
    Stretch,
    StretchAnalysis,
    SweepResult,
)

T = SafetyTag
FUNNEL = Funnel(silences=1, long_enough=1, with_cut=1, in_window=1, after_spacing_cap=1)


def cand(t):
    return Candidate(t=t, silence_start=t - 1, silence_end=t + 1, kind="hard")


def verdict(change=True, score=0.8):
    return BoundaryVerdict(is_scene_change=change, break_score=score, reason="r")


def scene(i, tags=()):
    return Scene(index=i, start=i * 100, end=(i + 1) * 100, stretch_indices=[i], summary="s",
                 dominant_activity="a", activity_tags=[], safety_tags=sorted(tags), unknown=False)  # fmt: skip


ANALYSIS = StretchAnalysis(summary="s", dominant_activity="a", setting="x", mood="m", confidence=0.9)
FOOD = Brand(id="food", name="Food", category="c", tagline="t", description="d", negative_tags=[T.DEATH_GRIEF],
             negative_contexts_raw=["death"])  # fmt: skip


def report(plans, verdicts, cands, vetoed=()):
    base = [scene(0), scene(1), scene(2)]
    swept = [scene(0), scene(1, {T.DEATH_GRIEF}), scene(2)]
    return build_debug(
        video="v.mp4", duration_s=300, funnel=FUNNEL, candidates=cands, verdicts=verdicts,
        stretches=[Stretch(index=i, start=i * 100, end=(i + 1) * 100) for i in range(3)],
        analyses=[ANALYSIS] * 3, traces=[[], [], []], base_scenes=base, scenes=swept,
        sweeps={1: SweepResult(safety_tags=[T.DEATH_GRIEF], evidence="a funeral insert", confidence=0.8)},
        plans=plans, vetoed_times=list(vetoed), brands=[FOOD], break_ids={100: "break-1"},
        min_break_score=0.5, llm_stats={}, loops=1, wall_s=1.0,
    )  # fmt: skip


def plan(t, status, brand_id=None, blocked=()):
    choice = BrandChoice(
        brand_id=brand_id,
        shortlist=[ShortlistEntry(brand_id="food", name="Food", similarity=0.4, fit=0.9, reason="r")],
        blocked=[BlockedModel(brand_id="food", tags=list(blocked))] if blocked else [],
        reason="x",
    )
    return BreakPlan(
        candidate=cand(t), break_score=0.8, before=0, after=1, status=status, choice=choice, reason="why"
    )


def test_every_candidate_gets_a_status_and_reason():
    cands = [cand(100), cand(200), cand(250), cand(280)]
    verdicts = [verdict(), verdict(False, 0.1), verdict(True, 0.4), verdict(True, 0.9)]
    out = report([plan(100, "approved", "food")], verdicts, cands)
    assert [c.status for c in out.candidates] == [
        "selected",
        "not_scene_change",
        "below_min_score",
        "pacing_rejected",
    ]
    assert all(c.reason for c in out.candidates)


def test_a_vetoed_candidate_is_reported_as_vetoed_with_the_reviewer_reason():
    out = report([plan(100, "dropped", "food")], [verdict()], [cand(100)], vetoed=[100])
    assert out.candidates[0].status == "vetoed"
    assert out.breaks[0].outcome == "dropped"


def test_break_record_shows_sweep_added_tags_and_the_blocking_tag():
    out = report([plan(100, "promo", None, blocked=["death_grief"])], [verdict()], [cand(100)])
    b = out.breaks[0]
    assert b.sweep_added == {"before": [], "after": [T.DEATH_GRIEF]}
    assert b.blocked[0].name == "Food" and b.blocked[0].tags == ["death_grief"]
    assert b.outcome == "promo" and b.brand_id is None


def test_scene_records_list_what_the_sweep_added():
    out = report([plan(100, "approved", "food")], [verdict()], [cand(100)])
    assert [s.sweep_added for s in out.scenes] == [[], [T.DEATH_GRIEF], []]
    assert out.scenes[1].sweep_evidence == "a funeral insert"


def test_an_approved_break_names_its_brand_and_id():
    out = report([plan(100, "approved", "food")], [verdict()], [cand(100)])
    b = out.breaks[0]
    assert (b.outcome, b.brand_id, b.brand_name, b.break_id) == ("brand", "food", "Food", "break-1")
