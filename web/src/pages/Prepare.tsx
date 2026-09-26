import { useEffect, useMemo, useState } from "react";
import { Label } from "../components/bits";
import { ProcessDialog, type RunSource } from "../components/ProcessDialog";
import { bytes, clock, titleOf } from "../lib/format";
import type { LibraryItem } from "../types";

/** What the person picked on Home: a file of theirs, or a sample on the server. */
export type Selection = { kind: "file"; file: File } | { kind: "sample"; item: LibraryItem };

/** The ready screen: a preview and the facts about the video, then Analyse or Back. Nothing starts before Analyse. */
export function Prepare({ selection }: { selection: Selection | null }) {
  const [run, setRun] = useState<RunSource | null>(null);
  const [duration, setDuration] = useState<number | null>(null);
  const file = selection?.kind === "file" ? selection.file : null;
  const url = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);

  useEffect(() => () => void (url && URL.revokeObjectURL(url)), [url]);
  useEffect(() => {
    if (!selection) location.hash = "#/";
  }, [selection]);
  if (!selection) return null;

  const src = selection.kind === "file" ? (url ?? "") : selection.item.video_url;
  const fileName = selection.kind === "file" ? selection.file.name : selection.item.video;
  const size = selection.kind === "file" ? selection.file.size : selection.item.size_bytes;
  const title = titleOf(fileName.replace(/\.[^.]+$/, ""));
  const source: RunSource = selection.kind === "file" ? { kind: "file", file: selection.file } : { kind: "sample", name: selection.item.name };

  return (
    <main id="main" tabIndex={-1} className="prepare">
      <Label>Ready to analyse</Label>
      <h1 className="prepare-title">{title}</h1>
      <div className="prepare-body">
        <video className="prepare-video" src={src} controls preload="metadata" onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)} aria-label={`Preview of ${fileName}`} />
        <div className="prepare-side">
          <dl className="facts">
            <div>
              <dt>File</dt>
              <dd className="facts-name">{fileName}</dd>
            </div>
            <div>
              <dt>Duration</dt>
              <dd className="tabular">{duration && Number.isFinite(duration) ? clock(duration) : "…"}</dd>
            </div>
            <div>
              <dt>Size</dt>
              <dd className="tabular">{bytes(size)}</dd>
            </div>
          </dl>
          <p className="muted">Analysing finds the natural pauses, understands each scene and places the brands that fit. Nothing is uploaded or run until you press Analyse.</p>
          <div className="actions">
            <button type="button" className="btn btn-primary" onClick={() => setRun(source)}>
              Analyse
            </button>
            <a className="btn btn-secondary" href="#/">
              Back
            </a>
          </div>
        </div>
      </div>
      {run && <ProcessDialog source={run} onDone={(name) => (location.hash = `#/video/${name}`)} />}
    </main>
  );
}
