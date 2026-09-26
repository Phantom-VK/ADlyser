import { useEffect, useRef, useState, type DragEvent } from "react";
import { ApiError, frameUrl, getLibrary, uploadVideo } from "../api";
import { Label } from "../components/bits";
import { clock, count } from "../lib/format";
import type { LibraryItem } from "../types";
import { titleOf } from "../lib/format";

/** A tile's image is a frame this far into the video, in seconds. */
const TILE_AT_S = 90;
/** The hero image is a frame this fraction of the way through the video. */
const HERO_AT = 0.3;
const ACCEPT = ".mp4,.mov,.mkv,.webm,video/*";

const meta = (item: LibraryItem): string =>
  item.processed && item.duration_s
    ? `${clock(item.duration_s)} · ${count(item.candidates, "candidate")} · ${item.breaks} selected`
    : "Not analysed yet";

function Tile({ item }: { item: LibraryItem }) {
  return (
    <a className="tile" href={`#/watch/${item.name}`}>
      <div className="tile-img">
        <img src={frameUrl(item.name, TILE_AT_S)} alt="" width={640} height={360} loading="lazy" decoding="async" />
        {!item.processed && <span className="tile-flag">Not analysed</span>}
      </div>
      <p className="tile-title">{titleOf(item.name)}</p>
      <p className="tile-meta tabular">{meta(item)}</p>
    </a>
  );
}

function UploadTile() {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState("");

  const send = async (file: File | undefined) => {
    if (!file) return;
    setError("");
    setProgress(0);
    try {
      location.hash = `#/watch/${await uploadVideo(file, setProgress)}`;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed.");
      setProgress(null);
    }
  };

  const drop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    void send(e.dataTransfer.files[0]);
  };

  return (
    <div
      className="tile tile-upload"
      data-over={over}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
    >
      <input ref={input} type="file" accept={ACCEPT} hidden onChange={(e) => void send(e.target.files?.[0])} />
      <div className="tile-img tile-drop">
        <Label>Analyse your own video</Label>
        <p className="muted">Drop a long-form video here to measure it, understand it and get a manifest.</p>
        {progress === null ? (
          <button type="button" className="btn btn-primary" onClick={() => input.current?.click()}>
            Choose video
          </button>
        ) : (
          <div className="progress" role="progressbar" aria-label="Upload" aria-valuenow={Math.round(progress * 100)} aria-valuemin={0} aria-valuemax={100}>
            <i style={{ width: `${(progress * 100).toFixed(0)}%` }} />
          </div>
        )}
      </div>
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function Shelf({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="shelf">
      <h2 className="shelf-title">{title}</h2>
      <div className="shelf-row">{children}</div>
    </section>
  );
}

/** The library: the latest analysis as a hero image, then shelves of episodes. */
export function Library() {
  const [items, setItems] = useState<LibraryItem[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getLibrary()
      .then(setItems)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Could not load the library."));
  }, []);

  const analysed = items?.filter((i) => i.processed) ?? [];
  const samples = items?.filter((i) => !i.uploaded) ?? [];
  const hero = analysed[0];

  return (
    <main id="main" tabIndex={-1} className="library">
      <section className="hero">
        {hero && hero.duration_s && (
          <img className="hero-img" src={frameUrl(hero.name, hero.duration_s * HERO_AT, "large")} alt="" width={1280} height={720} decoding="async" fetchPriority="high" />
        )}
        <div className="hero-copy">
          <Label>{hero ? "Latest analysis" : "Context-aware ad placement"}</Label>
          <h1>{hero ? titleOf(hero.name) : "Ad breaks that respect the story."}</h1>
          {hero && <p className="hero-meta tabular">{meta(hero)}</p>}
          <p className="hero-lead">
            ADlyser finds the natural pauses in a drama, understands each scene and places the brand that fits, and never one that shouldn't follow what was just watched.
          </p>
          {hero && (
            <div className="actions">
              <a className="btn btn-primary" href={`#/watch/${hero.name}`}>
                View analysis
              </a>
            </div>
          )}
        </div>
      </section>

      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      {!items && !error && <p className="muted library-status">Loading…</p>}
      {items && (
        <>
          {analysed.length > 0 && (
            <Shelf title="Recent analyses">
              {analysed.map((item) => (
                <Tile key={item.name} item={item} />
              ))}
            </Shelf>
          )}
          <Shelf title="Sample episodes">
            {samples.map((item) => (
              <Tile key={item.name} item={item} />
            ))}
            <UploadTile />
          </Shelf>
        </>
      )}
    </main>
  );
}
