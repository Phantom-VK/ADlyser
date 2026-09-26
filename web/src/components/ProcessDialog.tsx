import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { ApiError, followJob, runJob, uploadVideo } from "../api";
import { titleOf } from "../lib/format";
import { progressOf, type UploadPhase } from "../lib/steps";
import type { ProgressEvent } from "../types";
import { Label } from "./bits";

/** What the dialog runs: a chosen file (uploaded first), a video already on the server, a re-match, or a run already under way. */
export type RunSource =
  | { kind: "file"; file: File }
  | { kind: "sample"; name: string }
  | { kind: "rematch"; name: string }
  | { kind: "attach"; name: string };

interface Props {
  source: RunSource;
  /** Called with the video's name when the run has finished. */
  onDone: (name: string) => void;
}

const FOCUSABLE = "a[href], button:not(:disabled), input:not(:disabled), [tabindex]:not([tabindex='-1'])";
const STATE_TEXT = { pending: "Pending", running: "Running", done: "Done" } as const;

const heading = (s: RunSource): string =>
  s.kind === "file" ? `Analysing ${s.file.name}` : s.kind === "rematch" ? "Re-matching brands" : `Analysing ${titleOf(s.name)}`;

/**
 * A modal that runs the analysis and shows it: an overall bar, the steps, and the line about what is happening.
 * It cannot be dismissed while the run is going. A failure shows its message and a way home.
 */
export function ProcessDialog({ source, onDone }: Props) {
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [upload, setUpload] = useState<UploadPhase>(
    source.kind === "file" ? { kind: "uploading", fraction: 0 } : source.kind === "sample" ? { kind: "sent" } : { kind: "none" },
  );
  const [error, setError] = useState("");
  const box = useRef<HTMLDivElement>(null);
  const started = useRef(false);
  const alive = useRef(false);
  const stop = useRef<() => void>(() => {});
  const shown = useRef(0);
  const way = useRef<HTMLAnchorElement>(null);

  const done = useRef(onDone);
  done.current = onDone;
  const first = useRef(source);

  // The run starts once, on mount. (React's dev double-mount must not upload the file twice.)
  useEffect(() => {
    alive.current = true;
    const follow = (name: string) => {
      stop.current = followJob(
        name,
        (event) => alive.current && setEvents((all) => [...all, event]),
        (end) => {
          if (!alive.current) return;
          if (end.status === "done") done.current(name);
          else setError(end.error || "The analysis did not finish.");
        },
      );
    };
    if (!started.current) {
      started.current = true;
      const src = first.current;
      void (async () => {
        try {
          if (src.kind === "file") {
            const name = await uploadVideo(src.file, (fraction) => alive.current && setUpload({ kind: "uploading", fraction }));
            if (!alive.current) return;
            setUpload({ kind: "sent" });
            follow(name);
          } else {
            if (src.kind !== "attach") await runJob(src.name);
            if (alive.current) follow(src.name);
          }
        } catch (err) {
          if (alive.current) setError(err instanceof ApiError ? err.message : "Could not start the analysis.");
        }
      })();
    }
    return () => {
      alive.current = false;
      stop.current();
    };
  }, []);

  // Everything behind the dialog is inert while it is open; focus goes in and comes back when it closes.
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    const root = document.getElementById("root");
    root?.setAttribute("inert", "");
    box.current?.focus();
    return () => {
      root?.removeAttribute("inert");
      before?.focus?.();
    };
  }, []);

  useEffect(() => {
    if (error) way.current?.focus(); // a failed run: the way out is where focus goes
  }, [error]);

  const keys = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      if (error) location.hash = "#/";
      return;
    }
    if (e.key !== "Tab") return;
    const items = [...(box.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])];
    e.preventDefault();
    if (items.length === 0) return;
    const at = items.indexOf(document.activeElement as HTMLElement);
    items[(at + (e.shiftKey ? items.length - 1 : 1)) % items.length].focus();
  };

  const progress = progressOf(events, upload);
  shown.current = Math.max(shown.current, progress.fraction);
  const percent = Math.round(shown.current * 100);

  return createPortal(
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && e.preventDefault()}>
      <div ref={box} className="run" role="dialog" aria-modal="true" aria-labelledby="run-title" tabIndex={-1} onKeyDown={keys}>
        <Label>{error ? "Stopped" : "In progress"}</Label>
        <h2 id="run-title" className="run-title">
          {heading(source)}
        </h2>
        <div className="run-bar">
          <div className="progress" role="progressbar" aria-label="Overall progress" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
            <i style={{ width: `${percent}%` }} />
          </div>
          <span className="tabular">{percent}%</span>
        </div>
        <ol className="run-steps">
          {progress.steps.map((s) => (
            <li key={s.id} data-state={s.state}>
              <i className="run-mark" aria-hidden />
              <span>{s.label}</span>
              <em>{STATE_TEXT[s.state]}</em>
            </li>
          ))}
        </ol>
        {error ? (
          <>
            <p className="alert" role="alert">
              {error}
            </p>
            <div className="actions">
              <a ref={way} className="btn btn-primary" href="#/">
                Back to home
              </a>
            </div>
          </>
        ) : (
          <p className="run-detail" role="status">
            {progress.detail}
          </p>
        )}
      </div>
    </div>,
    document.body,
  );
}
