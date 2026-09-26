"""Review-node behaviour with the vision agents mocked (no API calls)."""

from pathlib import Path
from types import SimpleNamespace

from adlyser import graph
from adlyser.config import get_settings
from adlyser.graph import Pipeline, route_after_review
from adlyser.schemas import (
    Brand,
    BrandChoice,
    BreakPlan,
    Candidate,
    ReviewVerdict,
    SafetyTag,
    Scene,
    SweepResult,
)

T = SafetyTag
SETTINGS = get_settings()


def scene(i, tags=()):
    return Scene(index=i, start=i * 100, end=(i + 1) * 100, stretch_indices=[i], summary="s",
                 dominant_activity="a", activity_tags=[], safety_tags=sorted(tags), unknown=False)  # fmt: skip


FOOD = Brand(id="food", name="Food", category="c", tagline="t", description="d", negative_tags=[T.DEATH_GRIEF],
             negative_contexts_raw=["death"])  # fmt: skip


def plan(t=100, status="needs_review"):
    cand = Candidate(t=t, silence_start=t - 1, silence_end=t + 1, kind="hard")
    choice = BrandChoice(brand_id="food", shortlist=[], blocked=[], reason="x")
    return BreakPlan(candidate=cand, break_score=0.8, before=0, after=1, status=status, choice=choice)


def pipeline():
    pipe = object.__new__(Pipeline)
    pipe.settings, pipe.video, pipe.frames_dir = SETTINGS, Path("v.mp4"), Path("f")
    pipe.vision = SimpleNamespace()
    return pipe


def state(loops=0):
    return {"plans": [plan()], "scenes": [scene(0), scene(1)], "sweeps": {}, "excluded": [], "loops": loops,
            "brands": [FOOD], "perception": SimpleNamespace(speech=[], duration_s=1000.0)}  # fmt: skip


def mock(monkeypatch, sweep_tags=(), sweep_conf=0.9, verdict=None):
    async def fake_sweep(client, video, frames_dir, sc, settings):
        return SweepResult(safety_tags=list(sweep_tags), evidence="e", confidence=sweep_conf)

    async def fake_review(*args):
        return verdict or ReviewVerdict(decision="approve", reason="fine"), [{"tool": "look_closer"}]

    monkeypatch.setattr(graph, "sweep_scene", fake_sweep)
    monkeypatch.setattr(graph, "review_break", fake_review)


async def test_approve(monkeypatch):
    mock(monkeypatch)
    out = await pipeline().review(state())
    assert out["plans"][0].status == "approved" and out["plans"][0].review_trace == [{"tool": "look_closer"}]
    assert out["loops"] == 0 and not out["repace"]


async def test_a_sweep_that_adds_death_grief_blocks_the_chosen_food_brand_and_retries_the_match(monkeypatch):
    mock(monkeypatch, sweep_tags=[T.DEATH_GRIEF])
    out = await pipeline().review(state())
    p = out["plans"][0]
    assert p.status == "retry_brand" and "blocked after sweep: death_grief" in p.history[-1]
    assert p.review is None  # blocked in code, no reviewer call needed
    assert T.DEATH_GRIEF in out["scenes"][0].safety_tags and out["loops"] == 1
    assert route_after_review(out) == "match"


async def test_sweep_tags_are_only_added_never_removed(monkeypatch):
    mock(monkeypatch, sweep_tags=[T.VIOLENCE])
    s = state()
    s["scenes"] = [scene(0, {T.ALCOHOL}), scene(1)]
    out = await pipeline().review(s)
    assert set(out["scenes"][0].safety_tags) == {T.ALCOHOL, T.VIOLENCE}


async def test_a_failed_sweep_makes_the_scene_unknown_and_the_slot_a_promo(monkeypatch):
    mock(monkeypatch, sweep_conf=0.0)
    out = await pipeline().review(state())
    assert out["plans"][0].status == "promo" and out["scenes"][0].unknown and out["loops"] == 0


async def test_veto_next_brand_excludes_that_brand_and_loops_to_match(monkeypatch):
    mock(monkeypatch, verdict=ReviewVerdict(decision="veto", reason="hospital bed", retry="next_brand"))
    out = await pipeline().review(state())
    p = out["plans"][0]
    assert p.status == "retry_brand" and p.vetoed_brands == ["food"] and out["loops"] == 1
    assert route_after_review(out) == "match"


async def test_veto_next_candidate_drops_the_break_excludes_it_and_loops_to_pace(monkeypatch):
    mock(monkeypatch, verdict=ReviewVerdict(decision="veto", reason="mid-scene", retry="next_candidate"))
    out = await pipeline().review(state())
    assert out["plans"][0].status == "dropped" and out["excluded"] == [100.0]
    assert out["repace"] and out["loops"] == 1 and route_after_review(out) == "pace"


async def test_veto_promo_gives_a_promo_slot_without_looping(monkeypatch):
    mock(monkeypatch, verdict=ReviewVerdict(decision="veto", reason="tone", retry="promo"))
    out = await pipeline().review(state())
    assert out["plans"][0].status == "promo" and out["loops"] == 0 and route_after_review(out) == "emit"


async def test_loops_stop_at_the_limit(monkeypatch):
    limit = SETTINGS.reviewer.max_loops
    mock(monkeypatch, verdict=ReviewVerdict(decision="veto", reason="x", retry="next_brand"))
    out = await pipeline().review(state(loops=limit))
    assert out["plans"][0].status == "promo" and out["loops"] == limit and route_after_review(out) == "emit"
    mock(monkeypatch, verdict=ReviewVerdict(decision="veto", reason="x", retry="next_candidate"))
    out = await pipeline().review(state(loops=limit))
    assert out["plans"][0].status == "dropped" and out["excluded"] == [] and not out["repace"]
