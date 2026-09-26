import type { JobStatus, NodeEvent } from "../types";
import { Label } from "./bits";

interface Stage {
  id: string;
  label: string;
  note: string;
  /** Who does the work in this stage. */
  kind: string;
  /** The pipeline (LangGraph) nodes that belong to this stage. */
  nodes: string[];
}

/** The pipeline as an engineer reads it. Each stage groups the graph nodes that run together. */
const STAGES: Stage[] = [
  { id: "catalogue", label: "Catalogue", note: "Any format to brands", kind: "AI", nodes: ["catalogue"] },
  { id: "measure", label: "Measure", note: "Speech, silence, cuts", kind: "Tools", nodes: ["measure"] },
  { id: "understand", label: "Understand", note: "What happens between pauses", kind: "AI", nodes: ["analyse"] },
  { id: "boundary", label: "Boundary", note: "Real scene changes", kind: "AI", nodes: ["boundaries", "scenes"] },
  { id: "pacing", label: "Pacing", note: "Which breaks the rules allow", kind: "Code", nodes: ["pace"] },
  { id: "match", label: "Match", note: "Safety sweep, hard block, rank", kind: "AI + code", nodes: ["sweep", "match"] },
  { id: "review", label: "Review", note: "Approve or veto", kind: "AI", nodes: ["review", "settle", "finalize"] },
  { id: "vmap", label: "VMAP", note: "Manifest and debug JSON", kind: "Code", nodes: ["emit"] },
];
const ORDER = STAGES.flatMap((s) => s.nodes);

/** The node that is probably running: the one after the last finished node (after `settle` it can branch). */
function activeNode(events: NodeEvent[]): string | null {
  const last = events.length ? events[events.length - 1].node : null;
  if (last === null) return ORDER[0];
  if (last === "settle" || last === "emit") return null;
  return ORDER[ORDER.indexOf(last) + 1] ?? null;
}

interface Props {
  events: NodeEvent[];
  status: JobStatus;
  error?: string;
}

const TITLE: Record<JobStatus, string> = { idle: "Ready", running: "Running", done: "Complete", error: "Failed" };

/** The pipeline stages, lighting up as the server reports each node finishing. */
export function AgentGraph({ events, status, error }: Props) {
  const runs = new Map<string, { count: number; seconds: number }>();
  let prev = 0;
  for (const e of events) {
    const r = runs.get(e.node) ?? { count: 0, seconds: 0 };
    runs.set(e.node, { count: r.count + 1, seconds: r.seconds + Math.max(e.elapsed_s - prev, 0) });
    prev = e.elapsed_s;
  }
  const active = status === "running" || status === "error" ? activeNode(events) : null;
  const total = events.length ? events[events.length - 1].elapsed_s : 0;

  return (
    <section className="pipeline" aria-label="Pipeline progress">
      <header className="pipeline-head">
        <div>
          <Label>Pipeline</Label>
          <h2 className="pipeline-state" data-status={status} aria-live="polite">
            {TITLE[status]}
          </h2>
        </div>
        {total > 0 && <span className="muted tabular">{total.toFixed(1)}&nbsp;s</span>}
      </header>
      <ol className="stages">
        {STAGES.map((stage) => {
          const ran = stage.nodes.map((n) => runs.get(n));
          const isActive = active !== null && stage.nodes.includes(active);
          const state = isActive ? (status === "error" ? "failed" : "active") : ran.every(Boolean) ? "done" : "pending";
          const seconds = ran.reduce((sum, r) => sum + (r?.seconds ?? 0), 0);
          return (
            <li key={stage.id} className="stage" data-state={state}>
              <span className="stage-kind">{stage.kind}</span>
              <span className="stage-label">{stage.label}</span>
              <span className="stage-note">{stage.note}</span>
              <span className="stage-time tabular">{state === "done" ? `${seconds.toFixed(1)} s` : " "}</span>
              <span className="visually-hidden">{state}</span>
            </li>
          );
        })}
      </ol>
      {status === "error" && (
        <p className="alert" role="alert">
          {error || "The run failed."}
        </p>
      )}
    </section>
  );
}
