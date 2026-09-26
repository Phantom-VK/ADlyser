import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, getAddedBrands, getJob, getLibrary, getReport, getVmap } from "../api";
import { Label } from "../components/bits";
import { BrandsPanel, type RematchSummary } from "../components/BrandsPanel";
import type { PlayerHandle } from "../components/Player";
import { ProcessDialog, type RunSource } from "../components/ProcessDialog";
import { Timeline } from "../components/Timeline";
import { TracePanel } from "../components/TracePanel";
import { clock, count, titleOf } from "../lib/format";
import { STATUS_ORDER } from "../lib/status";
import { whyNoBreaks } from "../lib/why";
import { parseVmap, type AdBreak } from "../lib/vmap";
import type { AddedBrand, CandidateStatus, DebugReport, LibraryItem } from "../types";

// Video.js is the heaviest dependency, so it loads only when an episode opens.
const Player = lazy(() => import("../components/Player").then((m) => ({ default: m.Player })));

/** A shared link names a candidate by its time; it matches within this many seconds. */
const LINK_TOLERANCE_S = 0.05;

/** True when a run made no model call for scene analysis (it was all cached). */
const sceneCached = (r: DebugReport): boolean =>
  (r.llm_stats.stretch_analyst?.requests ?? 0) === 0 && (r.llm_stats.boundary_judge?.requests ?? 0) === 0;

interface Props {
  name: string;
  initialT: number | null;
  /** Reports which sections this page has, for the navigation. */
  onSections: (ids: string[]) => void;
  /** This video has no analysis yet: send the person to the ready screen for it. */
  onNeedsAnalysis: (item: LibraryItem) => void;
}

/** One episode: the player, the pipeline, the Decision Trace and the brands. */
export function Watch({ name, initialT, onSections, onNeedsAnalysis }: Props) {
  const [item, setItem] = useState<LibraryItem | null | undefined>(undefined);
  const [report, setReport] = useState<DebugReport | null>(null);
  const [breaks, setBreaks] = useState<AdBreak[]>([]);
  const [added, setAdded] = useState<AddedBrand[]>([]);
  const [run, setRun] = useState<RunSource | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [visible, setVisible] = useState<Set<CandidateStatus>>(new Set(STATUS_ORDER));
  const [summary, setSummary] = useState<RematchSummary | null>(null);
  const player = useRef<PlayerHandle>(null);
  const vmapText = useRef<string | null>(null);
  /** The manifest text from before a re-match started; undefined when no re-match is under way. */
  const rematchFrom = useRef<string | null | undefined>(undefined);

  const getTime = useCallback(() => player.current?.time() ?? 0, []);

  const loadResults = useCallback(async () => {
    const [rep, vmap] = await Promise.all([getReport(name), getVmap(name)]);
    vmapText.current = vmap;
    setReport(rep);
    setBreaks(vmap ? parseVmap(vmap) : []);
    setSelected((cur) => {
      if (cur !== null && rep?.candidates.some((c) => c.t === cur)) return cur;
      const linked = rep?.candidates.find((c) => initialT !== null && Math.abs(c.t - initialT) < LINK_TOLERANCE_S);
      if (linked) return linked.t;
      return (rep?.candidates.find((c) => c.status === "selected") ?? rep?.candidates[0])?.t ?? null;
    });
    return { rep, vmap };
  }, [name, initialT]);

  /** The run in the dialog has finished: show the new results, and what a re-match changed. */
  const finished = useCallback(() => {
    setRun(null);
    loadResults()
      .then(({ rep, vmap }) => {
        if (rematchFrom.current !== undefined && rep) setSummary({ sceneCached: sceneCached(rep), vmapChanged: vmap !== rematchFrom.current });
        rematchFrom.current = undefined;
      })
      .catch(() => setError("Could not load the new results."));
  }, [loadResults]);

  useEffect(() => {
    let alive = true;
    setItem(undefined);
    setReport(null);
    setBreaks([]);
    setRun(null);
    setSummary(null);
    setError("");
    (async () => {
      try {
        const [library, current, brands] = await Promise.all([getLibrary(), getJob(name), getAddedBrands()]);
        if (!alive) return;
        setItem(library.find((i) => i.name === name) ?? null);
        setAdded(brands);
        const { rep } = await loadResults();
        if (!alive) return;
        if (current.status === "running") setRun({ kind: "attach", name });
        else if (!rep) {
          const found = library.find((i) => i.name === name);
          if (found) onNeedsAnalysis(found);
        }
      } catch (err) {
        if (alive) setError(err instanceof ApiError ? err.message : "Could not load this episode.");
      }
    })();
    return () => {
      alive = false;
    };
  }, [name, loadResults, onNeedsAnalysis]);

  const rematch = useCallback(() => {
    rematchFrom.current = vmapText.current;
    setSummary(null);
    setRun({ kind: "rematch", name });
  }, [name]);

  useEffect(() => {
    onSections(report ? ["analysis", "trace", "brands"] : ["analysis"]);
    return () => onSections([]);
  }, [report, onSections]);

  useEffect(() => {
    if (selected !== null) history.replaceState(null, "", `#/video/${name}?t=${selected}`);
  }, [name, selected]);

  const candidate = useMemo(() => report?.candidates.find((c) => c.t === selected) ?? null, [report, selected]);
  const placed = useMemo(() => (report?.breaks ?? []).filter((b) => b.outcome !== "dropped").sort((a, b) => a.t - b.t), [report]);
  const toggle = (status: CandidateStatus) =>
    setVisible((v) => {
      const next = new Set(v);
      if (!next.delete(status)) next.add(status);
      return next;
    });
  const running = run !== null;

  if (item === undefined && !error) {
    return (
      <main id="main" tabIndex={-1} className="episode">
        <p className="muted">Loading…</p>
      </main>
    );
  }
  if (item === null) {
    return (
      <main id="main" tabIndex={-1} className="episode">
        <h1 className="episode-title">Video not found</h1>
        <p className="muted">There is no video called “{name}”.</p>
        <div className="actions">
          <a className="btn btn-secondary" href="#/">
            Back to home
          </a>
        </div>
      </main>
    );
  }

  return (
    <main id="main" tabIndex={-1} className="episode">
      <section id="analysis" className="block">
        <header className="episode-head">
          <div>
            <Label>
              <a href="#/">Home</a> / Episode
            </Label>
            <h1 className="episode-title">{titleOf(name)}</h1>
          </div>
          {report && (
            <dl className="stats">
              <div>
                <dt>Duration</dt>
                <dd className="tabular">{clock(report.duration_s)}</dd>
              </div>
              <div>
                <dt>Candidates</dt>
                <dd className="tabular">{report.candidates.length}</dd>
              </div>
              <div>
                <dt>Breaks</dt>
                <dd className="tabular">{placed.length}</dd>
              </div>
              {report.wall_s >= 1 && (
                <div>
                  <dt>Analysed in</dt>
                  <dd className="tabular">{report.wall_s.toFixed(0)}&nbsp;s</dd>
                </div>
              )}
            </dl>
          )}
          {report && (
            <div className="actions">
              <a className="btn btn-secondary" href={`/data/${name}/vmap.xml`} download={`${name}.vmap.xml`}>
                Download VMAP
              </a>
              <a className="btn btn-secondary" href={`/data/${name}/debug.json`} download={`${name}.debug.json`}>
                Download debug JSON
              </a>
            </div>
          )}
        </header>

        {error && (
          <p className="alert" role="alert">
            {error}
          </p>
        )}

        <div className="screen">
          {item && (
            <Suspense fallback={<div className="player player-loading" aria-busy="true" />}>
              <Player ref={player} videoUrl={item.video_url} breaks={breaks} />
            </Suspense>
          )}
          <aside className="breaks" aria-label="Ad breaks">
            {report ? (
              <>
                <div className="section-row">
                  <Label as="h2">Ad breaks</Label>
                  <span className="muted tabular">{count(placed.length, "break")}</span>
                </div>
                {placed.length === 0 ? (
                  <NoBreaks report={report} />
                ) : (
                  <ol className="break-list">
                    {placed.map((b) => (
                      <li key={b.t}>
                        <button type="button" data-selected={b.t === selected} onClick={() => { setSelected(b.t); document.getElementById("trace")?.scrollIntoView(); }}>
                          <span className="break-time tabular">{clock(b.t)}</span>
                          <span className="break-brand">{b.outcome === "promo" ? "Promo slot" : b.brand_name}</span>
                        </button>
                      </li>
                    ))}
                  </ol>
                )}
              </>
            ) : null}
          </aside>
        </div>
      </section>

      {report && (
        <>
          <section id="trace" className="block">
            <header className="section-head">
              <h2>Decision Trace</h2>
              <p className="muted tabular">
                {report.funnel.silences} silences → {report.funnel.with_cut} with a cut → {report.candidates.length} candidates → {placed.length} placed
                {report.intro_end ? ` · intro ends ${clock(report.intro_end)}` : ""}
                {report.outro_start != null ? ` · outro starts ${clock(report.outro_start)}` : ""}
              </p>
            </header>
            <Timeline
              duration={report.duration_s}
              scenes={report.scenes.map((s) => s.scene)}
              candidates={report.candidates}
              selected={selected}
              visible={visible}
              onToggle={toggle}
              onSelect={setSelected}
              onSeek={(t) => player.current?.seek(t)}
              getTime={getTime}
            />
            <TracePanel name={name} report={report} candidate={candidate} onPlay={(t) => player.current?.seek(t)} />
          </section>

          <section id="brands" className="block">
            <header className="section-head">
              <h2>Brands</h2>
              <p className="muted tabular">{count(report.brands.length, "brand")} in the catalogue</p>
            </header>
            <BrandsPanel report={report} added={added} busy={running} summary={summary} onAddedChange={() => getAddedBrands().then(setAdded)} onRematch={rematch} />
          </section>
        </>
      )}
      {run && <ProcessDialog source={run} onDone={finished} />}
    </main>
  );
}

/** Zero breaks is a result, so say why. */
function NoBreaks({ report }: { report: DebugReport }) {
  const why = whyNoBreaks(report);
  return (
    <div className="no-breaks">
      <p className="no-breaks-lead">No break placed. {why.lead}</p>
      <ul className="no-breaks-parts">
        {why.parts.map((p) => (
          <li key={p} className="tabular">
            {p}
          </li>
        ))}
      </ul>
    </div>
  );
}
