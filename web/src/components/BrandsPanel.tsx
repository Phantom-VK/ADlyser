import { useMemo, useState } from "react";
import { addBrand, ApiError, previewBrand, removeBrand } from "../api";
import { clock } from "../lib/format";
import type { AddedBrand, Brand, DebugReport } from "../types";
import { Label, Tags } from "./bits";

/** What the last re-match did, shown so it is clear no video was analysed again. */
export interface RematchSummary {
  sceneCached: boolean;
  vmapChanged: boolean;
}

interface Props {
  report: DebugReport | null;
  added: AddedBrand[];
  /** True while a job runs: adding and re-matching wait. */
  busy: boolean;
  summary: RematchSummary | null;
  onAddedChange: () => Promise<void>;
  onRematch: () => void;
}

const EXAMPLE = "Lotus Lassi, chilled yoghurt drinks. Best in summer scenes and family get-togethers. Never after funerals or hospital scenes.";

interface Fields {
  name: string;
  category: string;
  targets: string;
  negatives: string;
}
const EMPTY: Fields = { name: "", category: "", targets: "", negatives: "" };

/** The form's fields as one catalogue record. The normaliser reads any shape; these keys match the seed catalogue. */
const toRecord = (f: Fields): string =>
  JSON.stringify({ brand: f.name.trim(), sector: f.category.trim(), ideal_moments: f.targets.trim(), never_show_after: f.negatives.trim() });

function AddBrand({ busy, onAddedChange, onRematch }: Pick<Props, "busy" | "onAddedChange" | "onRematch">) {
  const [fields, setFields] = useState<Fields>(EMPTY);
  const [freeText, setFreeText] = useState(false);
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<Brand | null>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  const payload = freeText ? text : toRecord(fields);
  const ready = freeText ? text.trim().length > 0 : fields.name.trim().length > 0;

  const guard = async (work: () => Promise<void>) => {
    setWorking(true);
    setError("");
    try {
      await work();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setWorking(false);
    }
  };

  const normalise = () => guard(async () => setPreview(await previewBrand(payload)));
  const rematch = () =>
    guard(async () => {
      await addBrand(payload);
      await onAddedChange();
      setFields(EMPTY);
      setText("");
      setPreview(null);
      onRematch();
    });
  const edit = (patch: Partial<Fields>) => {
    setFields((f) => ({ ...f, ...patch }));
    setPreview(null);
  };

  return (
    <div className="add-brand">
      <div className="section-row">
        <Label as="h3">Add brand</Label>
        <button type="button" className="link" onClick={() => { setFreeText(!freeText); setPreview(null); }}>
          {freeText ? "Use the form" : "Paste JSON or text"}
        </button>
      </div>

      {freeText ? (
        <label className="field">
          <span>Catalogue entry</span>
          <textarea name="brand-text" rows={5} autoComplete="off" value={text} placeholder={`JSON, CSV or plain text. For example: ${EXAMPLE}…`} onChange={(e) => { setText(e.target.value); setPreview(null); }} disabled={busy} />
        </label>
      ) : (
        <div className="fields">
          <label className="field">
            <span>Brand name</span>
            <input name="brand-name" autoComplete="off" value={fields.name} placeholder="Lotus Lassi…" onChange={(e) => edit({ name: e.target.value })} disabled={busy} />
          </label>
          <label className="field">
            <span>Category</span>
            <input name="brand-category" autoComplete="off" value={fields.category} placeholder="Beverage…" onChange={(e) => edit({ category: e.target.value })} disabled={busy} />
          </label>
          <label className="field">
            <span>Target contexts</span>
            <input name="brand-targets" autoComplete="off" value={fields.targets} placeholder="Summer scenes, family get-togethers…" onChange={(e) => edit({ targets: e.target.value })} disabled={busy} />
          </label>
          <label className="field">
            <span>Negative contexts</span>
            <input name="brand-negatives" autoComplete="off" value={fields.negatives} placeholder="Funerals, hospital scenes…" onChange={(e) => edit({ negatives: e.target.value })} disabled={busy} />
          </label>
        </div>
      )}

      {preview ? (
        <div className="normalised">
          <p className="normalised-head">
            <span className="check" data-ok role="img" aria-label="done">✓</span> Brand normalized
          </p>
          <dl className="ledger">
            <div className="row-ledger"><dt>Name</dt><dd>{preview.name}</dd></div>
            <div className="row-ledger"><dt>Category</dt><dd>{preview.category}</dd></div>
            <div className="row-ledger"><dt>Fits</dt><dd>{preview.target_contexts.join(", ") || "Not stated"}</dd></div>
          </dl>
          <Label>Negative contexts</Label>
          <Tags tags={preview.negative_tags} tone="danger" empty="None declared" />
          <div className="actions">
            <button type="button" className="btn btn-primary" disabled={working || busy} onClick={rematch}>
              {working ? "Working…" : "Re-match"}
            </button>
            <button type="button" className="btn btn-quiet" onClick={() => setPreview(null)}>Edit</button>
          </div>
        </div>
      ) : (
        <div className="actions">
          <button type="button" className="btn btn-secondary" disabled={working || busy || !ready} onClick={normalise}>
            {working ? "Reading…" : "Normalize"}
          </button>
        </div>
      )}
      {error && <p className="alert" role="alert">{error}</p>}
    </div>
  );
}

/** The catalogue as the last run used it, where each brand was placed or blocked, and the add-a-brand flow. */
export function BrandsPanel({ report, added, busy, summary, onAddedChange, onRematch }: Props) {
  const [removing, setRemoving] = useState(false);

  const placed = useMemo(() => {
    const m = new Map<string, number[]>();
    report?.breaks.forEach((b) => b.outcome === "brand" && b.brand_id && m.set(b.brand_id, [...(m.get(b.brand_id) ?? []), b.t]));
    return m;
  }, [report]);
  const stats = useMemo(() => {
    const m = new Map<string, { blocked: number; best: number | null }>();
    report?.breaks.forEach((b) => {
      b.blocked.forEach((x) => {
        const cur = m.get(x.brand_id) ?? { blocked: 0, best: null };
        m.set(x.brand_id, { ...cur, blocked: cur.blocked + 1 });
      });
      b.shortlist.forEach((s) => {
        const cur = m.get(s.brand_id) ?? { blocked: 0, best: null };
        const fit = s.fit ?? s.similarity;
        m.set(s.brand_id, { ...cur, best: cur.best === null ? fit : Math.max(cur.best, fit) });
      });
    });
    return m;
  }, [report]);
  const known = new Set(report?.brands.map((b) => b.id));
  const pending = added.filter((a) => !known.has(a.id));
  const addedIds = new Set(added.map((a) => a.id));

  const remove = async (id: string) => {
    setRemoving(true);
    try {
      await removeBrand(id);
      await onAddedChange();
    } finally {
      setRemoving(false);
    }
  };

  return (
    <div className="brands-grid">
      <div className="brands-catalogue">
        {pending.length > 0 && (
          <div className="banner">
            <p>
              <b>{pending.map((p) => p.name).join(", ")}</b> {pending.length === 1 ? "is" : "are"} not matched in this episode yet. Scene analysis is cached, so a re-match takes seconds.
            </p>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={onRematch}>
              Re-match
            </button>
          </div>
        )}

        <div className="table-head" aria-hidden>
          <span>Brand</span>
          <span>Category</span>
          <span>Status</span>
        </div>
        <ul className="brand-table">
          {report?.brands.map((b) => {
            const where = placed.get(b.id) ?? [];
            const st = stats.get(b.id);
            return (
              <li key={b.id}>
                <details>
                  <summary>
                    <span className="brand-name">{b.name}</span>
                    <span className="muted">{b.category}</span>
                    <span className="brand-status" data-placed={where.length > 0}>
                      {where.length > 0 ? `Placed ${where.map(clock).join(", ")}` : "Active"}
                    </span>
                  </summary>
                  <div className="brand-detail">
                    <div>
                      <Label>Negative contexts</Label>
                      <Tags tags={b.negative_tags} tone="danger" empty="None declared" />
                      {b.negative_contexts_raw.length > 0 && <p className="note">Brand's words: {b.negative_contexts_raw.join(", ")}</p>}
                    </div>
                    <div>
                      <Label>Target contexts</Label>
                      <p className="muted">{b.target_contexts.join(", ") || "None stated"}</p>
                    </div>
                    <div>
                      <Label>In this episode</Label>
                      <p className="muted tabular">
                        {st?.best != null ? `Best match ${st.best.toFixed(2)}` : "Never shortlisted"}
                        {st && st.blocked > 0 ? ` · blocked at ${st.blocked} candidate${st.blocked === 1 ? "" : "s"}` : ""}
                      </p>
                    </div>
                    {addedIds.has(b.id) && (
                      <button type="button" className="btn btn-quiet" disabled={removing || busy} onClick={() => void remove(b.id)}>
                        Remove
                      </button>
                    )}
                  </div>
                </details>
              </li>
            );
          })}
          {pending.map((p) => (
            <li key={p.id} className="brand-pending">
              <span className="brand-name">{p.name}</span>
              <span className="muted">Not matched yet</span>
              <span className="brand-status" data-new>New</span>
              <button type="button" className="btn btn-quiet" disabled={removing || busy} onClick={() => void remove(p.id)}>
                Remove
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="brands-side">
        <AddBrand busy={busy} onAddedChange={onAddedChange} onRematch={onRematch} />
        {summary && (
          <div className="rematch" aria-live="polite">
            <Label as="h3">Re-match complete</Label>
            <p className="muted">No video re-analysis required.</p>
            <dl className="ledger">
              <div className="row-ledger"><dt>Scene intelligence</dt><dd className="state" data-tone={summary.sceneCached ? "ok" : "warn"}>{summary.sceneCached ? "Cached" : "Re-run"}</dd></div>
              <div className="row-ledger"><dt>Brand matching</dt><dd className="state" data-tone="ok">Updated</dd></div>
              <div className="row-ledger"><dt>VMAP</dt><dd className="state" data-tone={summary.vmapChanged ? "ok" : "neutral"}>{summary.vmapChanged ? "Updated" : "Unchanged"}</dd></div>
            </dl>
          </div>
        )}
      </div>
    </div>
  );
}
