import type { ReactNode } from "react";
import { frameUrl } from "../api";
import { clock, precise, tagLabel } from "../lib/format";
import { STATUS } from "../lib/status";
import type { BreakRecord, CandidateRecord, DebugReport, SceneInfo, ToolCall } from "../types";
import { Check, Label, Score, Tags, Thumb } from "./bits";

/** Frames shown either side of the cut, in seconds. */
const THUMB_OFFSET_S = 1.5;
const CUT: Record<CandidateRecord["kind"], string> = {
  hard: "Hard cut",
  black: "Fade to black",
  silence: "None",
};
const sceneName = (s: SceneInfo): string => `Scene ${String(s.index + 1).padStart(2, "0")}`;

interface Props {
  name: string;
  report: DebugReport;
  candidate: CandidateRecord | null;
  onPlay: (t: number) => void;
}

/** The scene that contains time `t`, or the last one. */
function sceneAt(scenes: SceneInfo[], t: number): SceneInfo | undefined {
  return scenes.find((s) => t >= s.start && t < s.end) ?? scenes[scenes.length - 1];
}

function toolText(call: ToolCall): string {
  const { t0, t1, n } = call.args;
  if (call.tool === "look_closer") return `Looked closer at ${clock(t0)}–${clock(t1)} · ${n ?? call.frames} frames`;
  if (call.tool === "speech_map") return `Checked the speech map ${clock(t0)}–${clock(t1)}`;
  return call.tool.replace(/_/g, " ");
}

/** Which side(s) of the break carry a tag. */
function sides(tag: string, before?: SceneInfo, after?: SceneInfo): string {
  const b = before?.safety_tags.includes(tag);
  const a = after?.safety_tags.includes(tag);
  if (b && a) return "both sides";
  if (b) return "before";
  if (a) return "after";
  return "";
}

function Row({ label, value, children }: { label: string; value?: ReactNode; children?: ReactNode }) {
  return (
    <div className="row-ledger">
      <dt>{label}</dt>
      <dd>{value}</dd>
      {children}
    </div>
  );
}

function SceneBlock({ scene, role, name, at, added }: { scene: SceneInfo; role: string; name: string; at: number; added: string[] }) {
  return (
    <article className="scene">
      <Thumb src={frameUrl(name, at)} alt={`${role}, frame at ${clock(at)}`} />
      <div className="scene-body">
        <Label>
          {role} · {sceneName(scene)} · {clock(scene.start)}–{clock(scene.end)}
        </Label>
        <p className="scene-activity">{scene.dominant_activity || "Unknown"}</p>
        <p className="scene-summary">{scene.summary || "The analysis failed, so this scene blocks every brand."}</p>
        {scene.unknown && <p className="flag">Unknown scene · blocks every brand</p>}
        <div className="scene-tags">
          <Tags tags={scene.safety_tags.filter((t) => !added.includes(t))} tone="warn" empty={added.length ? undefined : "No safety tags"} />
          <Tags tags={added} tone="danger" />
        </div>
        {added.length > 0 && <p className="note">Red tags were added by the reviewer's safety sweep.</p>}
      </div>
    </article>
  );
}

function BrandMatch({ record, before, after }: { record: BreakRecord; before?: SceneInfo; after?: SceneInfo }) {
  const empty = record.blocked.length === 0 && record.shortlist.length === 0;
  return (
    <section className="trace-section">
      <Label as="h3">Brand match</Label>
      {empty && <p className="muted">No brand was considered here.</p>}
      {!empty && (
        <ul className="match">
          {record.shortlist.map((s) => (
            <li key={s.brand_id} className="match-row" data-chosen={s.brand_id === record.brand_id}>
              <span className="match-name">{s.name}</span>
              <Score value={s.fit ?? s.similarity} label={s.fit === null ? "similarity" : "fit"} />
              {s.reason && <p className="match-why">{s.reason}</p>}
            </li>
          ))}
          {record.blocked.map((b) => (
            <li key={b.brand_id} className="match-row" data-blocked>
              <span className="match-name">{b.name}</span>
              <span className="match-blocked">Blocked</span>
              <p className="match-why">
                <span className="tags">
                  {b.tags.map((tag) => (
                    <span key={tag} className="tag" data-tone="danger">
                      {tagLabel(tag)}
                      {sides(tag, before, after) && <em>{sides(tag, before, after)}</em>}
                    </span>
                  ))}
                </span>
              </p>
            </li>
          ))}
        </ul>
      )}
      {record.blocked.length > 0 && (
        <p className="note">Enforced in code: a brand is blocked when any of its negative tags appears on either side of the break.</p>
      )}
    </section>
  );
}

/** The one-line outcome: what plays here, and why not if nothing does. */
function finalDecision(c: CandidateRecord, record?: BreakRecord): { title: string; tag: string; tone: "ok" | "warn" | "danger" | "neutral" } {
  if (c.status === "selected") {
    if (record?.outcome === "promo") return { title: "Promo slot", tag: "No brand allowed here", tone: "neutral" };
    return { title: record?.brand_name ?? "Break", tag: c.review?.decision === "approve" ? "Approved" : "Placed", tone: "ok" };
  }
  if (c.status === "vetoed") return { title: "No break", tag: "Vetoed by the reviewer", tone: "warn" };
  if (c.status === "blocked") return { title: "No break", tag: "Blocked", tone: "danger" };
  return { title: "No break", tag: STATUS[c.status].label, tone: "neutral" };
}

/** Everything the pipeline decided about one candidate pause, and why. */
export function TracePanel({ name, report, candidate, onPlay }: Props) {
  if (!candidate) {
    return (
      <div className="trace empty">
        <p className="muted">Select a marker on the timeline to see what was decided there, and why.</p>
      </div>
    );
  }
  const record = report.breaks.find((b) => b.t === candidate.t);
  const scenes = report.scenes.map((s) => s.scene);
  const before = record ? scenes[record.before_scene] : sceneAt(scenes, candidate.t - 0.01);
  const after = record ? scenes[record.after_scene] : sceneAt(scenes, candidate.t + 0.01);
  const sameScene = !candidate.is_scene_change || before?.index === after?.index;
  const review = candidate.review ?? record?.review ?? null;
  const trace = candidate.review_trace.length > 0 ? candidate.review_trace : (record?.review_trace ?? []);
  const decision = finalDecision(candidate, record);
  const meta = STATUS[candidate.status];
  // The outcome adds something only if it is not the boundary text or the reviewer's own words.
  const outcome =
    candidate.reason && candidate.reason !== candidate.boundary_reason && !(review && candidate.reason.includes(review.reason)) ? candidate.reason : "";
  // The reviewer's own words have their own section, so the steps keep only the others.
  const steps = (record?.history ?? []).filter((h) => !h.startsWith("reviewer"));

  return (
    <div className="trace" key={candidate.t}>
      <header className="trace-top">
        <div>
          <Label>Break candidate</Label>
          <h3 className="trace-time">{precise(candidate.t)}</h3>
          <p className="trace-scenes">
            {before && !sameScene ? `${sceneName(before)} → ${after ? sceneName(after) : ""}` : before ? sceneName(before) : ""}
            {before?.dominant_activity ? ` · ${before.dominant_activity}` : ""}
          </p>
        </div>
        <div className="trace-actions">
          <span className="status" data-status={candidate.status} data-shape={meta.shape}>
            <i className="glyph" aria-hidden />
            {meta.label}
          </span>
          <button type="button" className="btn btn-secondary" onClick={() => onPlay(Math.max(candidate.t - 8, 0))}>
            Play from here
          </button>
        </div>
      </header>

      <div className="trace-cols">
        <div className="trace-col">
          <section className="trace-section">
            <Label as="h3">Checks</Label>
            <dl className="ledger">
              <Row label="Silence" value={`${candidate.silence_s.toFixed(2)} s`}>
                <Check ok />
              </Row>
              <Row label="Speech at the cut" value="None">
                <Check ok />
              </Row>
              <Row label="Shot change" value={CUT[candidate.kind]}>
                <Check ok={candidate.kind !== "silence"} />
              </Row>
              <Row label="Scene change" value={candidate.is_scene_change ? "Confirmed" : "Same scene"}>
                <Check ok={candidate.is_scene_change} />
              </Row>
              <Row label="Break score" value={<Score value={candidate.break_score} label="break score" />} />
            </dl>
            <p className="reason">{candidate.boundary_reason}</p>
            {outcome && (
              <>
                <Label>Outcome</Label>
                <p className="reason">{outcome}</p>
              </>
            )}
          </section>

          <section className="trace-section">
            <Label as="h3">{sameScene ? "Scene" : "Scenes"}</Label>
            <div className="scenes">
              {before && !sameScene && <SceneBlock scene={before} role="Before" name={name} at={candidate.t - THUMB_OFFSET_S} added={record?.sweep_added.before ?? []} />}
              {after && !sameScene && <SceneBlock scene={after} role="After" name={name} at={candidate.t + THUMB_OFFSET_S} added={record?.sweep_added.after ?? []} />}
              {before && sameScene && <SceneBlock scene={before} role="Within" name={name} at={candidate.t} added={[]} />}
            </div>
          </section>
        </div>

        <div className="trace-col">
          {record && <BrandMatch record={record} before={before} after={after} />}

          {review && (
            <section className="trace-section">
              <Label as="h3">Reviewer</Label>
              <p className="verdict" data-tone={review.decision === "approve" ? "ok" : "warn"}>
                {review.decision === "approve" ? "Approved" : "Vetoed"}
              </p>
              <p className="reason">{review.reason}</p>
              {trace.length > 0 && (
                <ul className="tools">
                  {trace.map((call, i) => (
                    <li key={i}>{toolText(call)}</li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {steps.length > 0 && (
            <section className="trace-section">
              <Label as="h3">Steps</Label>
              <ol className="steps">
                {steps.map((h, i) => (
                  <li key={i}>{h}</li>
                ))}
              </ol>
            </section>
          )}

          <section className="trace-section decision" data-tone={decision.tone}>
            <Label as="h3">Final decision</Label>
            <p className="decision-title">{decision.title}</p>
            <p className="decision-tag">{decision.tag}</p>
          </section>
        </div>
      </div>
    </div>
  );
}
