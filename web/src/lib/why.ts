/** Why an analysed episode has no break: the plain-language answer, built from the candidate statuses. */
import type { CandidateStatus, DebugReport } from "../types";
import { STATUS, STATUS_ORDER } from "./status";
import { count } from "./format";

export interface NoBreakReason {
  lead: string;
  /** How many candidates ended in each state, most important first. */
  parts: string[];
}

export function whyNoBreaks(report: DebugReport): NoBreakReason {
  const { candidates, funnel, min_break_score: min } = report;
  if (candidates.length === 0) {
    return {
      lead: "No pause qualified as a break candidate.",
      parts: [`${funnel.silences} silences`, `${funnel.long_enough} long enough`, `${funnel.with_cut} with a cut`, `${funnel.in_window} inside the playable window`],
    };
  }
  const changes = candidates.filter((c) => c.is_scene_change);
  const tally = new Map<CandidateStatus, number>();
  candidates.forEach((c) => tally.set(c.status, (tally.get(c.status) ?? 0) + 1));
  const parts = STATUS_ORDER.filter((s) => tally.has(s)).map((s) => `${count(tally.get(s) ?? 0, "pause")} · ${STATUS[s].label.toLowerCase()}`);

  let lead: string;
  if (changes.length === 0) {
    lead = "No candidate pause was a scene change.";
  } else if (changes.every((c) => c.status === "below_min_score")) {
    const best = Math.max(...changes.map((c) => c.break_score));
    lead =
      min == null
        ? `No break point scored high enough. The best scored ${best.toFixed(2)}.`
        : `No break point scored ≥ ${min}. The best scored ${best.toFixed(2)}.`;
  } else {
    lead = "Every break point that scored well enough was blocked, vetoed or lost to the pacing rules.";
  }
  return { lead, parts };
}
