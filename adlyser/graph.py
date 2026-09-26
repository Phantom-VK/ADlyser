"""The pipeline as a LangGraph state graph.

catalogue, measure -> analyse -> boundaries -> scenes -> pace -> sweep -> match -> review -> settle -> finalize
-> emit. ``settle`` loops back to ``pace`` (another break point) or ``sweep`` then ``match`` (another brand),
at most ``reviewer.max_loops`` times. Node bodies are plain async methods; agents and rules stay
testable without the framework.
"""

import asyncio
import time
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from adlyser.agents.boundary_judge import judge_boundary
from adlyser.agents.brand_matcher import match_brand
from adlyser.agents.catalogue import normalise_catalogue, read_catalogue
from adlyser.agents.reviewer import review_break, sweep_scene
from adlyser.agents.stretch_analyst import analyse_stretch
from adlyser.cache import DiskCache, file_fingerprint
from adlyser.config import Settings
from adlyser.emit.creatives import make_slate
from adlyser.emit.debug import build_debug
from adlyser.emit.vmap import build_vmap
from adlyser.llm.client import make_clients
from adlyser.llm.embed import Embedder
from adlyser.log import get_logger
from adlyser.perception.measure import measure_signals
from adlyser.rules.candidates import find_candidates
from adlyser.rules.pacing import can_add, select_breaks
from adlyser.rules.safety import apply_sweep, blocking_tags
from adlyser.rules.scenes import build_scenes, make_stretches, scenes_around
from adlyser.schemas import (
    AdBreakSpec,
    BoundaryVerdict,
    Brand,
    BreakOption,
    BreakPlan,
    CandidateResult,
    Creative,
    DebugReport,
    Perception,
    Scene,
    Stretch,
    StretchAnalysis,
    SweepRecord,
)

log = get_logger(__name__)
RECURSION_LIMIT = 60


class State(TypedDict, total=False):
    """Everything the nodes pass along. Each node returns only the keys it changes."""

    perception: Perception
    found: CandidateResult
    stretches: list[Stretch]
    analyses: list[StretchAnalysis]
    traces: list[list[dict[str, Any]]]
    verdicts: list[BoundaryVerdict]
    base_scenes: list[Scene]
    scenes: list[Scene]
    options: list[BreakOption]
    brands: list[Brand]
    plans: list[BreakPlan]
    excluded: list[float]
    sweeps: dict[int, SweepRecord]
    loops: int
    repace: bool
    report: DebugReport
    vmap: str


def route_after_settle(state: State) -> str:
    """Where to go after the settle step: re-pace, re-match, or finalize.

    :param state: the graph state.
    :return: the next node name.
    """
    if state.get("repace"):
        return "pace"
    if any(p.status == "retry_brand" for p in state["plans"]):
        return "sweep"
    return "finalize"


class Pipeline:
    """Holds the clients and paths for one video and provides the graph nodes."""

    def __init__(self, video: Path, settings: Settings, out_dir: Path, base_url: str = "") -> None:
        """Create the pipeline for one video.

        :param video: path to the video.
        :param settings: loaded settings.
        :param out_dir: where vmap.xml and debug.json go.
        :param base_url: prefix for creative URLs (empty gives root-relative URLs).
        """
        self.video = video
        self.settings = settings
        self.out_dir = out_dir
        self.base_url = base_url
        self.vision, self.text = make_clients(settings)
        self.embedder = Embedder(settings.matcher.embed_model, DiskCache(settings.cache_dir / "embeddings"))
        self.frames_dir = settings.cache_dir / "frames" / file_fingerprint(video)
        self.started = time.perf_counter()

    async def catalogue(self, state: State) -> State:
        """Normalise the brand catalogue (cached; any format)."""
        raw = read_catalogue(self.settings.catalogue.path)
        return {"brands": await normalise_catalogue(self.text, raw)}

    async def measure(self, state: State) -> State:
        """Measure speech and cuts, then find candidate pauses and the stretches between them."""
        perception = await asyncio.to_thread(measure_signals, self.video, self.settings)
        found = find_candidates(
            perception.speech, perception.cuts, perception.duration_s, self.settings.candidates
        )
        return {
            "perception": perception,
            "found": found,
            "stretches": make_stretches(found.candidates, perception.duration_s),
        }

    async def analyse(self, state: State) -> State:
        """StretchAnalyst on every stretch, in parallel."""
        p = state["perception"]
        results = await asyncio.gather(
            *[
                analyse_stretch(
                    self.vision, self.video, self.frames_dir, s, p.transcript, p.duration_s, self.settings
                )
                for s in state["stretches"]
            ]
        )
        return {"analyses": [a for a, _ in results], "traces": [t for _, t in results]}

    async def boundaries(self, state: State) -> State:
        """BoundaryJudge on every candidate, in parallel."""
        p, analyses = state["perception"], state["analyses"]
        verdicts = await asyncio.gather(
            *[
                judge_boundary(
                    self.vision, self.video, self.frames_dir, c, analyses[i], analyses[i + 1],
                    p.transcript, p.duration_s, self.settings,
                )
                for i, c in enumerate(state["found"].candidates)
            ]
        )  # fmt: skip
        return {"verdicts": list(verdicts)}

    async def scenes(self, state: State) -> State:
        """Merge stretches into scenes and list the confirmed scene changes."""
        cands, verdicts = state["found"].candidates, state["verdicts"]
        scenes = build_scenes(
            state["stretches"],
            state["analyses"],
            [v.is_scene_change for v in verdicts],
            self.settings.scenes.min_confidence,
        )
        options = [
            BreakOption(candidate=c, break_score=v.break_score)
            for c, v in zip(cands, verdicts, strict=True)
            if v.is_scene_change
        ]
        return {"base_scenes": scenes, "scenes": scenes, "options": options, "plans": [], "excluded": [],
                "sweeps": {}, "loops": 0, "repace": False}  # fmt: skip

    async def pace(self, state: State) -> State:
        """PacingSolver: choose breaks among the confirmed changes the reviewer has not excluded."""
        excluded = set(state["excluded"])
        options = [o for o in state["options"] if o.candidate.t not in excluded]
        chosen = select_breaks(options, state["perception"].duration_s, self.settings.pacing)
        old = {p.candidate.t: p for p in state["plans"]}
        plans: list[BreakPlan] = []
        for o in chosen:
            t = o.candidate.t
            if t in old:
                plans.append(old[t])
                continue
            before, after = scenes_around(state["scenes"], t)
            plans.append(BreakPlan(candidate=o.candidate, break_score=o.break_score, before=before, after=after,
                                   status="needs_brand"))  # fmt: skip
        chosen_times = {p.candidate.t for p in plans}
        history = [p for p in state["plans"] if p.status == "dropped" and p.candidate.t not in chosen_times]
        return {"plans": [*plans, *history], "repace": False}

    async def sweep(self, state: State) -> State:
        """Safety sweep (BreakReviewer step 1) of the whole scene on each side of every break awaiting a brand.

        Runs before matching so the matcher and the hard block see the dense evidence, and so a sweep that
        covers a whole unknown scene can clear it. Sweeps are cached per scene for the whole run.
        """
        scenes, sweeps = list(state["scenes"]), dict(state["sweeps"])
        waiting = [p for p in state["plans"] if p.status in ("needs_brand", "retry_brand")]
        need = sorted({k for p in waiting for k in (p.before, p.after)} - set(sweeps))
        records = await asyncio.gather(
            *[sweep_scene(self.vision, self.video, self.frames_dir, scenes[k], self.settings) for k in need]
        )
        for k, record in zip(need, records, strict=True):
            sweeps[k] = record
            scenes[k] = apply_sweep(scenes[k], record)
        return {"scenes": scenes, "sweeps": sweeps}

    async def match(self, state: State) -> State:
        """BrandMatcher (reranks run in parallel across breaks). The hard block runs inside it."""
        scenes, brands = state["scenes"], state["brands"]
        plans = list(state["plans"])
        todo = [i for i, p in enumerate(plans) if p.status in ("needs_brand", "retry_brand")]
        choices = await asyncio.gather(
            *[
                match_brand(self.embedder, self.text, brands, scenes[plans[i].before], scenes[plans[i].after],
                            set(plans[i].vetoed_brands), self.settings.matcher)
                for i in todo
            ]
        )  # fmt: skip
        names = {b.id: b.name for b in brands}
        for i, choice in zip(todo, choices, strict=True):
            p = plans[i]
            if choice.kind == "brand":
                note, status = (
                    f"matched {names[choice.brand_id]} (fit {choice.shortlist[0].fit:.2f})",
                    "needs_review",
                )
            else:  # blocked, or no brand fits well: the same treatment (next-best break, promo as a last resort)
                note, status = f"no brand for this break: {choice.reason}", "blocked"
            plans[i] = p.model_copy(update={"choice": choice, "status": status, "history": [*p.history, note],
                                            "reason": note})  # fmt: skip
        return {"plans": plans}

    async def review(self, state: State) -> State:
        """BreakReviewer step 2: hard block once more on the swept scenes, then review each break."""
        st = self.settings
        plans, scenes = list(state["plans"]), state["scenes"]
        brands = {b.id: b for b in state["brands"]}
        to_review: list[int] = []
        for i, p in enumerate(plans):
            if p.status != "needs_review":
                continue
            tags = blocking_tags(brands[p.choice.brand_id], scenes[p.before], scenes[p.after])  # type: ignore[union-attr]
            if tags:
                note = f"blocked at review: {', '.join(tags)}"
                plans[i] = p.model_copy(
                    update={"status": "retry_brand", "history": [*p.history, note], "reason": note}
                )
            else:
                to_review.append(i)

        perception = state["perception"]
        reviews = await asyncio.gather(
            *[
                review_break(self.vision, self.video, self.frames_dir, perception.speech, perception.duration_s,
                             plans[i].candidate, scenes[plans[i].before], scenes[plans[i].after],
                             brands[plans[i].choice.brand_id], st)  # type: ignore[union-attr]
                for i in to_review
            ]
        )  # fmt: skip
        for i, (verdict, trace) in zip(to_review, reviews, strict=True):
            p = plans[i]
            update: dict[str, Any] = {"review": verdict, "review_trace": trace,
                                      "history": [*p.history, f"reviewer {verdict.decision}: {verdict.reason}"]}  # fmt: skip
            if verdict.decision == "approve":
                update.update(status="approved", reason=f"reviewer approved: {verdict.reason}")
            else:
                status = {"next_brand": "retry_brand", "next_candidate": "retry_candidate"}.get(
                    verdict.retry or "", "promo"
                )
                brand_id = p.choice.brand_id  # type: ignore[union-attr]
                update.update(status=status, reason=f"reviewer vetoed: {verdict.reason}",
                              vetoed_brands=[*p.vetoed_brands, brand_id] if status == "retry_brand" else p.vetoed_brands)  # fmt: skip
            plans[i] = p.model_copy(update=update)
        return {"plans": plans}

    async def settle(self, state: State) -> State:
        """Decide what needs another pass: another break point, or another brand, within the loop budget.

        A break with no allowed brand (blocked) or a vetoed break point is excluded from pacing so the solver
        picks the next-best option. A blocked break stays in the plan list: ``finalize`` turns it into a
        promo slot if there is room, once the loops are used up.
        """
        excluded, plans = list(state["excluded"]), list(state["plans"])
        exhausted = state["loops"] >= self.settings.reviewer.max_loops
        repace = retry_brand = False
        for i, p in enumerate(plans):
            t = p.candidate.t
            if p.status == "retry_candidate":
                note = "loop limit reached: break dropped" if exhausted else "trying the next break point"
                plans[i] = p.model_copy(update={"status": "dropped", "reason": f"{p.reason}; {note}"})
            if p.status in ("retry_candidate", "blocked") and not exhausted and t not in excluded:
                excluded.append(t)
                repace = True
            elif p.status == "retry_brand":
                if exhausted:
                    plans[i] = p.model_copy(
                        update={"status": "promo", "reason": f"{p.reason}; loop limit reached: promo slot"}
                    )
                else:
                    retry_brand = True
        return {"plans": plans, "excluded": excluded, "repace": repace,
                "loops": state["loops"] + 1 if repace or retry_brand else state["loops"]}  # fmt: skip

    async def finalize(self, state: State) -> State:
        """Turn breaks that are still blocked into promo slots where the pacing rules leave room, else drop them."""
        pacing, duration = self.settings.pacing, state["perception"].duration_s
        plans = list(state["plans"])
        placed = [p.candidate.t for p in plans if p.status in ("approved", "promo")]
        blocked = sorted(
            (i for i, p in enumerate(plans) if p.status == "blocked"), key=lambda i: -plans[i].break_score
        )
        for i in blocked:
            p = plans[i]
            if can_add(placed, p.candidate.t, duration, pacing):
                placed.append(p.candidate.t)
                note = "no allowed brand and no better break point: promo slot"
                plans[i] = p.model_copy(
                    update={"status": "promo", "history": [*p.history, note], "reason": note}
                )
            else:
                note = "no allowed brand and no room for a promo under the pacing rules: dropped"
                plans[i] = p.model_copy(
                    update={"status": "dropped", "history": [*p.history, note], "reason": note}
                )
        return {"plans": plans}

    async def emit(self, state: State) -> State:
        """Write the brand and promo slates, vmap.xml and debug.json."""
        st = self.settings
        live = sorted(
            (p for p in state["plans"] if p.status in ("approved", "promo")), key=lambda p: p.candidate.t
        )
        brands = {b.id: b for b in state["brands"]}
        creatives_dir = st.data_dir / "creatives"

        async def creative(ad_id: str, title: str, subtitle: str) -> Creative:
            path = creatives_dir / f"{ad_id}.mp4"
            if not path.exists():
                await asyncio.to_thread(make_slate, title, subtitle, path, st.creatives)
            return Creative(ad_id=ad_id, title=title, duration_s=st.creatives.duration_s,
                            media_url=f"{self.base_url}/{path.as_posix()}", width=st.creatives.width,
                            height=st.creatives.height)  # fmt: skip

        specs: list[AdBreakSpec] = []
        break_ids: dict[float, str] = {}
        for n, p in enumerate(live, 1):
            if p.status == "approved":
                b = brands[p.choice.brand_id]  # type: ignore[union-attr]
                c = await creative(b.id, b.name, b.tagline)
            else:
                c = await creative("promo", st.creatives.promo_title, st.creatives.promo_subtitle)
            break_ids[p.candidate.t] = f"break-{n}"
            specs.append(AdBreakSpec(break_id=f"break-{n}", time_s=p.candidate.t, creative=c))

        perception, found = state["perception"], state["found"]
        stats: dict[str, dict[str, int]] = {}
        for client in (self.vision, self.text):
            stats.update({k: dict(v) for k, v in client.stats.items()})
        report = build_debug(
            video=perception.video, duration_s=perception.duration_s, funnel=found.funnel,
            candidates=found.candidates, verdicts=state["verdicts"], stretches=state["stretches"],
            analyses=state["analyses"], traces=state["traces"], base_scenes=state["base_scenes"],
            scenes=state["scenes"], sweeps=state["sweeps"], plans=state["plans"], vetoed_times=state["excluded"],
            brands=state["brands"], break_ids=break_ids, min_break_score=st.pacing.min_break_score,
            llm_stats=stats, loops=state["loops"], wall_s=round(time.perf_counter() - self.started, 1),
        )  # fmt: skip
        vmap = build_vmap(specs)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "vmap.xml").write_text(vmap)
        (self.out_dir / "debug.json").write_text(report.model_dump_json(indent=1))
        return {"report": report, "vmap": vmap}

    def build(self) -> Any:
        """Wire the graph. After ``settle`` the loop goes back to ``pace`` or ``sweep`` (then match), or on."""
        g = StateGraph(State)
        for name, fn in [
            ("catalogue", self.catalogue), ("measure", self.measure), ("analyse", self.analyse),
            ("boundaries", self.boundaries), ("scenes", self.scenes), ("pace", self.pace),
            ("sweep", self.sweep), ("match", self.match), ("review", self.review),
            ("settle", self.settle), ("finalize", self.finalize), ("emit", self.emit),
        ]:  # fmt: skip
            g.add_node(name, fn)
        chain = [
            "catalogue",
            "measure",
            "analyse",
            "boundaries",
            "scenes",
            "pace",
            "sweep",
            "match",
            "review",
            "settle",
        ]
        g.add_edge(START, chain[0])
        for a, b in pairwise(chain):
            g.add_edge(a, b)
        g.add_conditional_edges(
            "settle", route_after_settle, {"pace": "pace", "sweep": "sweep", "finalize": "finalize"}
        )
        g.add_edge("finalize", "emit")
        g.add_edge("emit", END)
        return g.compile()


async def run_pipeline(
    video: Path,
    settings: Settings,
    out_dir: Path,
    base_url: str = "",
    on_event: Callable[[str, float], None] | None = None,
) -> DebugReport:
    """Run the whole pipeline on one video and write vmap.xml and debug.json to ``out_dir``.

    :param video: path to the video.
    :param settings: loaded settings.
    :param out_dir: output directory.
    :param base_url: prefix for creative URLs.
    :param on_event: called as ``on_event(node, elapsed_s)`` when each node finishes (progress events).
    :return: the debug report.
    :raises AdlyserError: if measurement or the catalogue cannot be read (LLM failures fall back safely).
    """
    pipe = Pipeline(video, settings, out_dir, base_url)
    preload = asyncio.create_task(pipe.embedder.preload())  # overlaps the model load with measurement
    final: State = {}
    async for chunk in pipe.build().astream(
        {}, stream_mode="updates", config={"recursion_limit": RECURSION_LIMIT}
    ):
        for node, update in chunk.items():
            final.update(update)
            elapsed = round(time.perf_counter() - pipe.started, 1)
            log.info("node_done", extra={"node": node, "elapsed_s": elapsed})
            if on_event:
                on_event(node, elapsed)
    await preload
    return final["report"]
