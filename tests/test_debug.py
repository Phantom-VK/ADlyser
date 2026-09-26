from adlyser.emit.debug import build_debug
from adlyser.schemas import Blocked as BlockedModel
from adlyser.schemas import (
    BoundaryVerdict,
    Brand,
    BrandChoice,
    BreakPlan,
    Candidate,
    Funnel,
    ReviewVerdict,
    SafetyTag,
    Scene,
    ShortlistEntry,
    Stretch,
    StretchAnalysis,
    SweepRecord,
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


def report(plans, verdicts, cands, excluded=None):
    base = [scene(0), scene(1), scene(2)]
    swept = [scene(0), scene(1, {T.DEATH_GRIEF}), scene(2)]
    return build_debug(
        video="v.mp4", duration_s=300, funnel=FUNNEL, candidates=cands, verdicts=verdicts,
        stretches=[Stretch(index=i, start=i * 100, end=(i + 1) * 100) for i in range(3)],
        analyses=[ANALYSIS] * 3, traces=[[], [], []], base_scenes=base, scenes=swept,
        sweeps={1: SweepRecord(safety_tags=[T.DEATH_GRIEF], unsure_tags=[], evidence="a funeral insert", ok=True, full_coverage=True, frames=9)},
        plans=plans, excluded_reasons=excluded or {}, brands=[FOOD], break_ids={100: "break-1"},
        min_break_score=0.5, llm_stats={}, loops=1, wall_s=1.0,
    )  # fmt: skip


def plan(t, status, brand_id=None, blocked=()):
    choice = BrandChoice(
        kind="brand" if brand_id else "blocked",
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


def test_a_vetoed_candidate_carries_the_reviewers_reason_and_tool_calls():
    verdict_ = ReviewVerdict(
        decision="veto", reason="a hospital bed is visible at 12:03", retry="next_candidate"
    )
    vetoed = plan(100, "dropped", "food").model_copy(
        update={
            "review": verdict_,
            "review_trace": [{"tool": "look_closer", "args": {"t0": 720, "t1": 740, "n": 3}, "frames": 3}],
            "reason": "reviewer vetoed: a hospital bed is visible at 12:03; trying the next break point",
        }
    )
    out = report([vetoed], [verdict()], [cand(100)])
    c = out.candidates[0]
    assert c.status == "vetoed" and "hospital bed" in c.reason
    assert (
        c.review.reason == "a hospital bed is visible at 12:03" and c.review_trace[0]["tool"] == "look_closer"
    )
    assert out.breaks[0].outcome == "dropped"


def test_a_blocked_and_excluded_break_is_reported_as_blocked_not_vetoed():
    blocked = plan(100, "blocked", None, blocked=["violence"]).model_copy(
        update={"reason": "no brand for this break: every brand is blocked"}
    )
    out = report([blocked], [verdict()], [cand(100)])
    assert out.candidates[0].status == "blocked" and out.candidates[0].review is None


def test_a_neighbour_excluded_with_the_all_blocking_scene_is_blocked_with_that_reason():
    out = report(
        [],
        [verdict(), verdict()],
        [cand(100), cand(200)],
        excluded={200: "touches scene 1, which blocks every brand"},
    )
    assert out.candidates[1].status == "blocked" and "scene 1" in out.candidates[1].reason
    assert out.candidates[0].status == "pacing_rejected"


def test_break_record_shows_sweep_added_tags_and_the_blocking_tag():
    out = report([plan(100, "promo", None, blocked=["death_grief"])], [verdict()], [cand(100)])
    b = out.breaks[0]
    assert b.sweep_added == {"before": [], "after": [T.DEATH_GRIEF]}
    assert b.blocked[0].name == "Food" and b.blocked[0].tags == ["death_grief"]
    assert b.outcome == "promo" and b.brand_id is None


def test_scene_records_list_what_the_sweep_added():
    out = report([plan(100, "approved", "food")], [verdict()], [cand(100)])
    assert [s.sweep_added for s in out.scenes] == [[], [T.DEATH_GRIEF], []]
    assert out.scenes[1].sweep.evidence == "a funeral insert" and out.scenes[1].sweep.full_coverage


def test_an_approved_break_names_its_brand_and_id():
    out = report([plan(100, "approved", "food")], [verdict()], [cand(100)])
    b = out.breaks[0]
    assert (b.outcome, b.brand_id, b.brand_name, b.break_id) == ("brand", "food", "Food", "break-1")


def test_the_report_records_the_score_threshold_so_the_ui_can_explain_zero_breaks():
    out = report([], [verdict(True, 0.3)], [cand(100)])
    assert out.min_break_score == 0.5 and out.candidates[0].status == "below_min_score"
