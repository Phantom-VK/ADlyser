"""Graph node behaviour with the agents mocked (no API calls)."""

from pathlib import Path
from types import SimpleNamespace

from adlyser import graph
from adlyser.config import get_settings
from adlyser.errors import PerceptionError
from adlyser.graph import Pipeline, route_after_settle
from adlyser.schemas import (
    Brand,
    BrandChoice,
    BreakOption,
    BreakPlan,
    Candidate,
    ReviewVerdict,
    SafetyTag,
    Scene,
    ShortlistEntry,
    SweepRecord,
)

T = SafetyTag
SETTINGS = get_settings()
MAX_LOOPS = SETTINGS.reviewer.max_loops


def scene(i, tags=(), unknown=False, start=None, end=None):
    return Scene(
        index=i,
        start=i * 500 if start is None else start,
        end=(i + 1) * 500 if end is None else end,
        stretch_indices=[i],
        summary="s",
        dominant_activity="a",
        activity_tags=[],
        safety_tags=sorted(tags),
        unknown=unknown,
    )


def cand(t):
    return Candidate(t=t, silence_start=t - 1, silence_end=t + 1, kind="hard")


FOOD = Brand(id="food", name="Food", category="c", tagline="t", description="d", negative_tags=[T.DEATH_GRIEF],
             negative_contexts_raw=["death"])  # fmt: skip
RIDES = Brand(id="rides", name="Rides", category="c", tagline="t", description="d", negative_tags=[],
              negative_contexts_raw=[])  # fmt: skip


def choice(kind="brand", brand_id="food"):
    entry = ShortlistEntry(brand_id="food", name="Food", similarity=0.5, fit=0.9, reason="r")
    return BrandChoice(
        kind=kind, brand_id=brand_id if kind == "brand" else None, shortlist=[entry], blocked=[], reason="x"
    )


def plan(t=500, status="needs_review", kind="brand", score=0.8, before=0, after=1):
    return BreakPlan(candidate=cand(t), break_score=score, before=before, after=after, status=status,
                     choice=choice(kind) if kind else None)  # fmt: skip


def pipeline():
    pipe = object.__new__(Pipeline)
    pipe.settings, pipe.video, pipe.frames_dir = SETTINGS, Path("v.mp4"), Path("f")
    pipe.vision = pipe.text = pipe.embedder = SimpleNamespace()
    return pipe


def state(plans=None, scenes=None, loops=0, excluded=(), sweeps=None):
    return {
        "plans": plans if plans is not None else [plan()],
        "scenes": scenes or [scene(0), scene(1), scene(2)],
        "sweeps": sweeps or {},
        "excluded": list(excluded),
        "excluded_reasons": {},
        "options": [],
        "loops": loops,
        "repace": False,
        "brands": [FOOD, RIDES],
        "perception": SimpleNamespace(speech=[], duration_s=3600.0),
    }


def record(tags=(), unsure=(), ok=True, full=True):
    return SweepRecord(
        safety_tags=list(tags), unsure_tags=list(unsure), evidence="e", ok=ok, full_coverage=full, frames=5
    )


def mock_sweep(monkeypatch, rec, calls=None):
    async def fake(client, video, frames_dir, sc, settings):
        if calls is not None:
            calls.append(sc.index)
        return rec

    monkeypatch.setattr(graph, "sweep_scene", fake)


# ---- sweep node ------------------------------------------------------------


async def test_sweep_adds_seen_and_unsure_tags_to_both_sides_of_the_break(monkeypatch):
    mock_sweep(monkeypatch, record([T.ALCOHOL], unsure=[T.DEATH_GRIEF]))
    out = await pipeline().sweep(state([plan(status="needs_brand")]))
    assert set(out["scenes"][0].safety_tags) == {T.ALCOHOL, T.DEATH_GRIEF}
    assert set(out["scenes"][1].safety_tags) == {T.ALCOHOL, T.DEATH_GRIEF}
    assert set(out["sweeps"]) == {0, 1}


async def test_each_scene_is_swept_only_once(monkeypatch):
    calls = []
    mock_sweep(monkeypatch, record(), calls)
    pipe = pipeline()
    first = await pipe.sweep(state([plan(status="needs_brand")]))
    second_state = state([plan(status="retry_brand")], scenes=first["scenes"], sweeps=first["sweeps"])
    await pipe.sweep(second_state)
    assert calls == [0, 1]


async def test_a_full_coverage_sweep_clears_an_unknown_scene_before_matching(monkeypatch):
    mock_sweep(monkeypatch, record([T.ALCOHOL]))
    out = await pipeline().sweep(
        state([plan(status="needs_brand")], scenes=[scene(0, unknown=True), scene(1)])
    )
    assert not out["scenes"][0].unknown


async def test_a_failed_or_capped_sweep_leaves_the_scene_unknown(monkeypatch):
    for rec in (record(ok=False), record(full=False)):
        mock_sweep(monkeypatch, rec)
        out = await pipeline().sweep(
            state([plan(status="needs_brand")], scenes=[scene(0, unknown=True), scene(1)])
        )
        assert out["scenes"][0].unknown


# ---- match node ------------------------------------------------------------


def mock_match(monkeypatch, kind):
    async def fake(embedder, client, brands, before, after, excluded, cfg):
        return choice(kind)

    monkeypatch.setattr(graph, "match_brand", fake)


async def test_a_poor_fit_is_treated_like_a_blocked_break_so_pacing_can_try_another(monkeypatch):
    mock_match(monkeypatch, "no_fit")
    out = await pipeline().match(state([plan(status="needs_brand", kind=None)]))
    settled = await pipeline().settle(state(out["plans"]))
    assert settled["excluded"] == [500] and settled["repace"]


async def test_match_sets_the_status_from_the_choice_kind(monkeypatch):
    for kind, status in [("brand", "needs_review"), ("blocked", "blocked"), ("no_fit", "blocked")]:
        mock_match(monkeypatch, kind)
        out = await pipeline().match(state([plan(status="needs_brand", kind=None)]))
        assert out["plans"][0].status == status


# ---- review node -----------------------------------------------------------


def mock_review(monkeypatch, verdict):
    async def fake(*args):
        return verdict, [{"tool": "look_closer"}]

    monkeypatch.setattr(graph, "review_break", fake)


async def test_approve(monkeypatch):
    mock_review(monkeypatch, ReviewVerdict(decision="approve", reason="fine"))
    out = await pipeline().review(state())
    assert out["plans"][0].status == "approved" and out["plans"][0].review_trace == [{"tool": "look_closer"}]


async def test_a_brand_blocked_by_the_swept_scenes_is_not_reviewed(monkeypatch):
    mock_review(monkeypatch, ReviewVerdict(decision="approve", reason="fine"))
    out = await pipeline().review(state(scenes=[scene(0, {T.DEATH_GRIEF}), scene(1)]))
    p = out["plans"][0]
    assert p.status == "retry_brand" and p.review is None and "death_grief" in p.history[-1]


async def test_veto_outcomes(monkeypatch):
    for retry, status in [
        ("next_brand", "retry_brand"),
        ("next_candidate", "retry_candidate"),
        ("promo", "promo"),
    ]:
        mock_review(monkeypatch, ReviewVerdict(decision="veto", reason="x", retry=retry))
        out = await pipeline().review(state())
        assert out["plans"][0].status == status
    assert out["plans"][0].review.decision == "veto"


async def test_a_vetoed_brand_is_remembered_for_the_rematch(monkeypatch):
    mock_review(monkeypatch, ReviewVerdict(decision="veto", reason="x", retry="next_brand"))
    out = await pipeline().review(state())
    assert out["plans"][0].vetoed_brands == ["food"]


# ---- settle / route --------------------------------------------------------


async def test_a_blocked_break_is_excluded_and_the_solver_is_asked_for_the_next_best_break():
    out = await pipeline().settle(state([plan(status="blocked", kind="blocked")]))
    assert out["excluded"] == [500] and out["repace"] and out["loops"] == 1
    assert out["plans"][0].status == "blocked"  # kept, so finalize can still fall back to a promo
    assert route_after_settle(out | {"plans": out["plans"]}) == "pace"


async def test_a_blocked_break_stays_blocked_when_the_loops_are_used_up():
    out = await pipeline().settle(state([plan(status="blocked", kind="blocked")], loops=MAX_LOOPS))
    assert out["excluded"] == [] and not out["repace"] and out["loops"] == MAX_LOOPS
    assert route_after_settle(out) == "finalize"


async def test_an_already_excluded_blocked_break_does_not_trigger_another_loop():
    out = await pipeline().settle(state([plan(status="blocked", kind="blocked")], excluded=[500]))
    assert not out["repace"] and out["loops"] == 0


async def test_veto_next_candidate_drops_the_break_and_loops_to_pace():
    out = await pipeline().settle(state([plan(status="retry_candidate")]))
    assert out["plans"][0].status == "dropped" and out["excluded"] == [500] and out["repace"]


async def test_veto_next_candidate_at_the_limit_drops_without_looping():
    out = await pipeline().settle(state([plan(status="retry_candidate")], loops=MAX_LOOPS))
    assert out["plans"][0].status == "dropped" and out["excluded"] == [] and not out["repace"]


async def test_retry_brand_loops_to_the_sweep_and_match_or_becomes_a_promo_at_the_limit():
    out = await pipeline().settle(state([plan(status="retry_brand")]))
    assert out["loops"] == 1 and route_after_settle(out) == "sweep"
    out = await pipeline().settle(state([plan(status="retry_brand")], loops=MAX_LOOPS))
    assert out["plans"][0].status == "promo" and route_after_settle(out) == "finalize"


async def test_nothing_to_retry_goes_to_finalize():
    out = await pipeline().settle(state([plan(status="approved")]))
    assert out["loops"] == 0 and route_after_settle(out) == "finalize"


# ---- finalize --------------------------------------------------------------


async def test_a_no_fit_break_falls_back_to_a_promo_when_pacing_has_room():
    out = await pipeline().finalize(state([plan(500, "blocked", "no_fit")]))
    assert out["plans"][0].status == "promo"


async def test_a_break_where_every_brand_is_blocked_or_the_scene_is_unknown_is_dropped_not_a_promo():
    out = await pipeline().finalize(state([plan(500, "blocked", "blocked")]))
    assert out["plans"][0].status == "dropped" and "dropped" in out["plans"][0].reason


async def test_a_no_fit_break_is_dropped_when_it_would_break_the_pacing_rules():
    plans = [plan(500, "approved"), plan(600, "blocked", "no_fit")]  # 100 s apart, min gap is 300
    out = await pipeline().finalize(state(plans))
    assert [p.status for p in out["plans"]] == ["approved", "dropped"]


async def test_no_fit_breaks_compete_for_room_by_score():
    plans = [plan(500, "blocked", "no_fit", score=0.6), plan(600, "blocked", "no_fit", score=0.9)]
    out = await pipeline().finalize(state(plans))
    assert [p.status for p in out["plans"]] == ["dropped", "promo"]


# ---- pace ------------------------------------------------------------------


async def test_pace_picks_the_next_best_option_once_a_break_point_is_excluded():
    options = [
        BreakOption(candidate=cand(500), break_score=0.9),
        BreakOption(candidate=cand(1000), break_score=0.8),
    ]
    base = state([], scenes=[scene(0), scene(1), scene(2)], excluded=[500])
    base["options"] = options
    base["perception"] = SimpleNamespace(
        speech=[], duration_s=1800.0
    )  # room for 3 breaks, but only one is left
    out = await pipeline().pace(base)
    assert [p.candidate.t for p in out["plans"]] == [1000]
    assert out["plans"][0].status == "needs_brand" and (out["plans"][0].before, out["plans"][0].after) == (
        1,
        2,
    )


async def test_re_pacing_pins_approved_breaks_and_keeps_every_plan_in_the_history():
    options = [
        BreakOption(candidate=cand(t), break_score=s) for t, s in [(500, 0.6), (1000, 0.9), (1500, 0.95)]
    ]
    plans = [plan(500, "approved"), plan(1000, "retry_candidate")]
    base = state(plans, scenes=[scene(0), scene(1), scene(2), scene(3)], excluded=[1000])
    base["options"], base["perception"] = options, SimpleNamespace(speech=[], duration_s=1800.0)
    settled = await pipeline().settle(base)
    base.update(settled)
    out = await pipeline().pace(base)
    by_t = {p.candidate.t: p.status for p in out["plans"]}
    assert by_t[500] == "approved" and by_t[1500] == "needs_brand"  # cap is 3: 500 kept, 1500 added
    assert by_t[1000] == "dropped"  # the excluded break is still in the list


async def test_re_pacing_keeps_an_approved_break_the_solver_would_otherwise_swap_out():
    options = [BreakOption(candidate=cand(t), break_score=s) for t, s in [(500, 0.55), (700, 0.99)]]
    base = state([plan(500, "approved")], scenes=[scene(0), scene(1), scene(2)])
    base["options"] = options
    base["perception"] = SimpleNamespace(speech=[], duration_s=1800.0)
    out = await pipeline().pace(base)  # 700 is 200 s from 500, under the 300 s gap
    assert [(p.candidate.t, p.status) for p in out["plans"]] == [(500, "approved")]


async def test_every_status_survives_a_re_pace():
    plans = [
        plan(500, "approved"),
        plan(1000, "promo"),
        plan(2000, "dropped"),
        plan(2500, "blocked", "no_fit"),
    ]
    base = state(plans, scenes=[scene(0), scene(1), scene(2), scene(3)])
    base["options"], base["perception"] = [], SimpleNamespace(speech=[], duration_s=3600.0)
    out = await pipeline().pace(base)
    assert sorted((p.candidate.t, p.status) for p in out["plans"]) == [
        (500, "approved"), (1000, "promo"), (2000, "dropped"), (2500, "blocked"),
    ]  # fmt: skip


# ---- measure node ----------------------------------------------------------------------------------


def measure_pipeline(monkeypatch, transcribe):
    perception = SimpleNamespace(speech=[], cuts=[], duration_s=600.0, transcript=[])
    monkeypatch.setattr(graph, "measure_signals", lambda video, settings: perception)
    monkeypatch.setattr(graph, "measure_transcript", transcribe)
    return pipeline(), perception


async def test_the_measure_node_adds_the_transcript_through_measure_transcript(monkeypatch):
    seen = []

    def add(perception, settings):
        seen.append(perception)
        return SimpleNamespace(speech=[], cuts=[], duration_s=600.0, transcript=["hello"])

    pipe, perception = measure_pipeline(monkeypatch, add)
    out = await pipe.measure({})
    assert seen == [perception] and out["perception"].transcript == ["hello"]


async def test_a_failed_transcript_never_stops_the_run(monkeypatch):
    def boom(perception, settings):
        raise PerceptionError("whisper crashed")

    pipe, perception = measure_pipeline(monkeypatch, boom)
    out = await pipe.measure({})
    assert out["perception"] is perception and out["found"].candidates == []


# ---- neighbours of an all-blocking scene ----------------------------------------------------


def all_blocking_scenes():
    """Scenes 0|1|2|3 with boundaries at 500, 1000, 1500. Scene 1 (violence) blocks every brand."""
    return [scene(0), scene(1, {T.VIOLENCE}), scene(2), scene(3)]


VIOLENT = Brand(id="v", name="V", category="c", tagline="t", description="d", negative_tags=[T.VIOLENCE],
                negative_contexts_raw=[])  # fmt: skip
OPTIONS = [BreakOption(candidate=cand(t), break_score=s) for t, s in [(500, 0.9), (1000, 0.85), (1500, 0.8)]]


async def test_options_touching_an_all_blocking_scene_are_excluded_together_and_neither_is_retried():
    st = state([plan(500, "blocked", "blocked", before=0, after=1)], scenes=all_blocking_scenes())
    st["brands"], st["options"] = [VIOLENT], OPTIONS
    out = await pipeline().settle(st)
    assert set(out["excluded"]) == {500, 1000} and 1500 not in out["excluded"]
    assert "scene 1" in out["excluded_reasons"][1000] and out["repace"]


async def test_pacing_then_picks_a_third_option_elsewhere():
    st = state([plan(500, "blocked", "blocked", before=0, after=1)], scenes=all_blocking_scenes())
    st["brands"], st["options"] = [VIOLENT], OPTIONS
    settled = await pipeline().settle(st)
    st.update(settled)
    st["perception"] = SimpleNamespace(speech=[], duration_s=3600.0)
    out = await pipeline().pace(st)
    live = [p for p in out["plans"] if p.status == "needs_brand"]
    assert [p.candidate.t for p in live] == [1500]
    assert [p.candidate.t for p in out["plans"] if p.status == "blocked"] == [
        500
    ]  # kept for the promo fallback


async def test_a_break_blocked_only_by_the_union_of_two_scenes_excludes_just_itself():
    brands = [Brand(id="a", name="A", category="c", tagline="t", description="d", negative_tags=[T.VIOLENCE],
                    negative_contexts_raw=[]),
              Brand(id="b", name="B", category="c", tagline="t", description="d", negative_tags=[T.ALCOHOL],
                    negative_contexts_raw=[])]  # fmt: skip
    scenes = [scene(0, {T.VIOLENCE}), scene(1, {T.ALCOHOL}), scene(2), scene(3)]
    st = state([plan(500, "blocked", "blocked", before=0, after=1)], scenes=scenes)
    st["brands"], st["options"] = brands, OPTIONS
    out = await pipeline().settle(st)
    assert out["excluded"] == [500]


async def test_a_no_fit_break_does_not_exclude_its_neighbours():
    p = plan(500, "blocked", "no_fit", before=0, after=1)
    st = state([p], scenes=all_blocking_scenes())
    st["brands"], st["options"] = [VIOLENT], OPTIONS
    out = await pipeline().settle(st)
    assert out["excluded"] == [500]
