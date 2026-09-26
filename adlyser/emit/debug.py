"""debug.json: every candidate and break with its evidence and reason. Pure function, no I/O."""

from adlyser.schemas import (
    BlockedRecord,
    BoundaryVerdict,
    Brand,
    BreakPlan,
    BreakRecord,
    Candidate,
    CandidateRecord,
    DebugReport,
    Funnel,
    Scene,
    SceneRecord,
    Stretch,
    StretchAnalysis,
    StretchRecord,
    SweepRecord,
)


def _candidate_record(
    cand: Candidate,
    verdict: BoundaryVerdict,
    plan: BreakPlan | None,
    excluded_reason: str | None,
    min_break_score: float,
) -> CandidateRecord:
    """Classify one candidate: not a scene change, too weak, rejected by pacing, selected, vetoed or blocked."""
    review, trace = (plan.review, plan.review_trace) if plan else (None, [])
    if not verdict.is_scene_change:
        status, reason = "not_scene_change", verdict.reason
    elif verdict.break_score < min_break_score:
        status, reason = "below_min_score", f"break_score {verdict.break_score:.2f} below {min_break_score}"
    elif plan is not None and plan.status in ("approved", "promo"):
        status, reason = "selected", plan.reason
    elif plan is not None and plan.review is not None and plan.review.decision == "veto":
        status, reason = "vetoed", plan.reason
    elif plan is not None:
        status, reason = "blocked", plan.reason
    elif excluded_reason is not None:
        status, reason = "blocked", excluded_reason
    else:
        status, reason = "pacing_rejected", "not chosen by the pacing solver (gap, hourly or ad-load cap)"
    return CandidateRecord(
        t=cand.t,
        silence_s=cand.silence_s,
        kind=cand.kind,
        is_scene_change=verdict.is_scene_change,
        break_score=verdict.break_score,
        boundary_reason=verdict.reason,
        status=status,
        reason=reason,
        review=review,
        review_trace=trace,
    )


def build_debug(
    *,
    video: str,
    duration_s: float,
    funnel: Funnel,
    candidates: list[Candidate],
    verdicts: list[BoundaryVerdict],
    stretches: list[Stretch],
    analyses: list[StretchAnalysis],
    traces: list[list[dict]],
    base_scenes: list[Scene],
    scenes: list[Scene],
    sweeps: dict[int, SweepRecord],
    plans: list[BreakPlan],
    excluded_reasons: dict[float, str],
    brands: list[Brand],
    break_ids: dict[float, str],
    min_break_score: float,
    intro_end: float = 0.0,
    outro_start: float | None = None,
    llm_stats: dict[str, dict[str, int]],
    loops: int,
    wall_s: float,
) -> DebugReport:
    """Assemble the debug report from the final pipeline state.

    :param video: video file name.
    :param duration_s: video length.
    :param funnel: candidate funnel counts.
    :param candidates: all candidate pauses.
    :param verdicts: one BoundaryJudge verdict per candidate.
    :param stretches: stretches between candidates.
    :param analyses: one StretchAnalyst result per stretch.
    :param traces: tool calls made per stretch.
    :param base_scenes: scenes before any sweep.
    :param scenes: scenes after the safety sweep.
    :param sweeps: sweep results by scene index.
    :param plans: every planned break, including dropped ones.
    :param excluded_reasons: why candidate times were excluded from pacing without a plan of their own.
    :param brands: the catalogue.
    :param break_ids: manifest break id by candidate time.
    :param min_break_score: pacing threshold, for the candidate status.
    :param intro_end: where the opening titles end (0 = none).
    :param outro_start: where the closing titles start (None = none).
    :param llm_stats: call statistics by prompt.
    :param loops: veto loops used.
    :param wall_s: run time in seconds.
    :return: the report.
    """
    by_t = {p.candidate.t: p for p in plans}
    names = {b.id: b.name for b in brands}
    records = [
        _candidate_record(c, v, by_t.get(c.t), excluded_reasons.get(c.t), min_break_score)
        for c, v in zip(candidates, verdicts, strict=True)
    ]
    scene_records = []
    for base, now in zip(base_scenes, scenes, strict=True):
        scene_records.append(
            SceneRecord(
                scene=now,
                sweep_added=sorted(set(now.safety_tags) - set(base.safety_tags)),
                sweep=sweeps.get(now.index),
                unknown_before_sweep=base.unknown,
            )
        )
    break_records = []
    for plan in sorted(plans, key=lambda p: p.candidate.t):
        added = {
            side: sorted(set(scenes[i].safety_tags) - set(base_scenes[i].safety_tags))
            for side, i in (("before", plan.before), ("after", plan.after))
        }
        bid = plan.choice.brand_id if plan.choice else None
        outcome = (
            "dropped" if plan.status == "dropped" else ("brand" if plan.status == "approved" else "promo")
        )
        break_records.append(
            BreakRecord(
                break_id=break_ids.get(plan.candidate.t),
                t=plan.candidate.t,
                break_score=plan.break_score,
                outcome=outcome,
                brand_id=bid if outcome == "brand" else None,
                brand_name=names.get(bid) if outcome == "brand" and bid else None,
                before_scene=plan.before,
                after_scene=plan.after,
                shortlist=plan.choice.shortlist if plan.choice else [],
                blocked=[
                    BlockedRecord(brand_id=b.brand_id, name=names.get(b.brand_id, b.brand_id), tags=b.tags)
                    for b in (plan.choice.blocked if plan.choice else [])
                ],
                sweep_added=added,
                review=plan.review,
                review_trace=plan.review_trace,
                history=plan.history,
                reason=plan.reason,
            )
        )
    return DebugReport(
        video=video,
        duration_s=duration_s,
        funnel=funnel,
        candidates=records,
        stretches=[
            StretchRecord(stretch=s, analysis=a, tool_trace=t)
            for s, a, t in zip(stretches, analyses, traces, strict=True)
        ],
        scenes=scene_records,
        breaks=break_records,
        brands=brands,
        llm_stats=llm_stats,
        loops=loops,
        wall_s=wall_s,
        min_break_score=min_break_score,
        intro_end=intro_end,
        outro_start=outro_start,
    )
