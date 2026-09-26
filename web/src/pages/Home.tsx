import { useEffect, useRef, useState, type DragEvent } from "react";
import { ApiError, frameUrl, getConfig, getLibrary, getVideos } from "../api";
import { Label } from "../components/bits";
import { bytes, clock, count, titleOf, when } from "../lib/format";
import type { AnalysedVideo, AppConfig, LibraryItem } from "../types";
import type { Selection } from "./Prepare";

/** A card's image is a frame this far into the video, in seconds. */
const CARD_AT_S = 90;
/** An analysed video's card shows a frame this fraction of the way through. */
const ANALYSED_AT = 0.3;

/** Why a file cannot be taken, or null when it can. */
function problem(file: File, config: AppConfig): string | null {
  const dot = file.name.lastIndexOf(".");
  const suffix = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
  if (!config.upload_suffixes.includes(suffix)) return `Only ${config.upload_suffixes.join(", ")} files are accepted.`;
  if (file.size > config.upload_max_mb * 1024 * 1024) return `That file is over ${config.upload_max_mb} MB.`;
  return null;
}

function UploadBox({ config, onChoose }: { config: AppConfig | null; onChoose: (s: Selection) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [error, setError] = useState("");

  const take = (file: File | undefined) => {
    if (!file || !config) return;
    const why = problem(file, config);
    if (why) setError(why);
    else onChoose({ kind: "file", file });
  };
  const drop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    take(e.dataTransfer.files[0]);
  };

  return (
    <section
      className="dropbox"
      data-over={over}
      aria-label="Upload a video"
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
    >
      <input
        ref={input}
        type="file"
        accept={config ? config.upload_suffixes.join(",") : undefined}
        hidden
        onChange={(e) => {
          take(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      <Label>Analyse a video</Label>
      <h1 className="dropbox-title">Drop a video here, or choose a file</h1>
      <p className="muted">
        {config ? `${config.upload_suffixes.join(" ")} · up to ${config.upload_max_mb} MB` : " "}
      </p>
      <div className="actions">
        <button type="button" className="btn btn-primary" disabled={!config} onClick={() => input.current?.click()}>
          Choose file
        </button>
      </div>
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

function AnalysedCard({ video }: { video: AnalysedVideo }) {
  return (
    <a className="card" href={`#/video/${video.name}`}>
      <div className="card-img">
        <img src={frameUrl(video.name, (video.duration_s ?? 0) * ANALYSED_AT)} alt="" width={640} height={360} loading="lazy" decoding="async" />
      </div>
      <p className="card-title">{titleOf(video.name)}</p>
      <p className="card-meta tabular">
        {clock(video.duration_s ?? 0)} · {count(video.breaks, "break")}
      </p>
      <p className="card-meta tabular">{when(video.analysed_at)}</p>
    </a>
  );
}

function SampleCard({ item, onChoose }: { item: LibraryItem; onChoose: (s: Selection) => void }) {
  return (
    <button type="button" className="card" onClick={() => onChoose({ kind: "sample", item })}>
      <div className="card-img">
        <img src={frameUrl(item.name, CARD_AT_S)} alt="" width={640} height={360} loading="lazy" decoding="async" />
      </div>
      <p className="card-title">{titleOf(item.name)}</p>
      <p className="card-meta tabular">{bytes(item.size_bytes)}</p>
    </button>
  );
}

/** Home: the upload box, the analyses so far (from the server), and the sample videos not yet analysed. */
export function Home({ onChoose }: { onChoose: (s: Selection) => void }) {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [videos, setVideos] = useState<AnalysedVideo[] | null>(null);
  const [library, setLibrary] = useState<LibraryItem[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    Promise.all([getConfig(), getVideos(), getLibrary()])
      .then(([c, v, l]) => {
        if (!alive) return;
        setConfig(c);
        setVideos(v);
        setLibrary(l);
      })
      .catch((err: unknown) => alive && setError(err instanceof ApiError ? err.message : "Could not load your videos."));
    return () => {
      alive = false;
    };
  }, []);

  const samples = library?.filter((i) => !i.processed && !i.uploaded) ?? [];

  return (
    <main id="main" tabIndex={-1} className="home">
      <UploadBox config={config} onChoose={onChoose} />
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      {!videos && !error && <p className="muted home-status">Loading…</p>}
      {videos && videos.length > 0 && (
        <section className="home-section" aria-labelledby="recent">
          <h2 id="recent" className="section-title">
            Recently analysed
          </h2>
          <div className="card-grid">
            {videos.map((v) => (
              <AnalysedCard key={v.name} video={v} />
            ))}
          </div>
        </section>
      )}
      {samples.length > 0 && (
        <section className="home-section" aria-labelledby="samples">
          <h2 id="samples" className="section-title">
            Sample videos
          </h2>
          <div className="card-grid">
            {samples.map((item) => (
              <SampleCard key={item.name} item={item} onChoose={onChoose} />
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
