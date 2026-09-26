/** The steps a run goes through, as the processing dialog lists them, and where a run is in them. */
import type { ProgressEvent } from "../types";

export type StepState = "pending" | "running" | "done";

interface StepDef {
  id: string;
  label: string;
  /** The step is done once this pipeline node has finished (or, for `stage`, once that milestone was reported). */
  node?: string;
  stage?: string;
}

const UPLOAD: StepDef = { id: "upload", label: "Upload" };
const PIPELINE: StepDef[] = [
  { id: "measure", label: "Measure audio & cuts", stage: "signals" },
  { id: "pauses", label: "Find pauses", node: "measure" },
  { id: "analyse", label: "Analyse stretches", node: "analyse" },
  { id: "boundaries", label: "Judge boundaries", node: "boundaries" },
  { id: "pace", label: "Scenes & pacing", node: "pace" },
  { id: "sweep", label: "Safety sweep", node: "sweep" },
  { id: "match", label: "Match brands", node: "match" },
  { id: "review", label: "Review", node: "review" },
  { id: "emit", label: "Build manifest", node: "emit" },
];

/** Where the file is: uploading it, already on the server, or not part of this run (a re-match). */
export type UploadPhase = { kind: "uploading"; fraction: number } | { kind: "sent" } | { kind: "none" };

export interface Step {
  id: string;
  label: string;
  state: StepState;
}

export interface Progress {
  steps: Step[];
  /** 0..1 over the whole run; a step that is running counts by how far it has got. */
  fraction: number;
  /** What is happening now, in a line. */
  detail: string;
}

/** Progress of a run from the events received so far. */
export function progressOf(events: ProgressEvent[], upload: UploadPhase, finished = false): Progress {
  const defs = upload.kind === "none" ? PIPELINE : [UPLOAD, ...PIPELINE];
  const nodes = new Set(events.filter((e) => e.type === "node").map((e) => e.node));
  const stages = new Set(events.flatMap((e) => (e.type === "detail" && e.stage ? [e.stage] : [])));
  const done = (d: StepDef): boolean =>
    finished ||
    (d === UPLOAD ? upload.kind === "sent" : (d.node !== undefined && nodes.has(d.node)) || (d.stage !== undefined && stages.has(d.stage)));

  const firstOpen = defs.findIndex((d) => !done(d));
  const steps: Step[] = defs.map((d, i) => ({
    id: d.id,
    label: d.label,
    state: firstOpen === -1 || i < firstOpen ? "done" : i === firstOpen ? "running" : "pending",
  }));

  const latest = [...events].reverse().find((e): e is Extract<ProgressEvent, { type: "detail" }> => e.type === "detail");
  let partial = 0;
  let detail = "Working…";
  if (finished) detail = "Done";
  else if (firstOpen !== -1) {
    const running = defs[firstOpen];
    if (running === UPLOAD) {
      partial = upload.kind === "uploading" ? upload.fraction : 0;
      detail = `Uploading ${Math.round(partial * 100)}%`;
    } else {
      if (latest) {
        detail = latest.text;
        if (latest.total) partial = Math.min((latest.done ?? 0) / latest.total, 1);
      } else {
        detail = running.label;
      }
    }
  }
  const doneCount = steps.filter((s) => s.state === "done").length;
  return { steps, fraction: Math.min((doneCount + partial) / defs.length, 1), detail };
}
