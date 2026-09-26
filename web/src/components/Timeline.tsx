import { useEffect, useMemo, useRef, type CSSProperties, type KeyboardEvent, type PointerEvent } from "react";
import { clock } from "../lib/format";
import { STATUS, STATUS_ORDER } from "../lib/status";
import type { CandidateRecord, CandidateStatus, SceneInfo } from "../types";

interface Props {
  duration: number;
  scenes: SceneInfo[];
  candidates: CandidateRecord[];
  /** The selected candidate's time. */
  selected: number | null;
  /** Statuses currently shown. */
  visible: Set<CandidateStatus>;
  onToggle: (status: CandidateStatus) => void;
  onSelect: (t: number) => void;
  onSeek: (t: number) => void;
  /** The content position in seconds, read every frame while the page is open. */
  getTime: () => number;
}

/** Axis label spacing, in seconds: the smallest step that keeps the axis to about six labels. */
const AXIS_STEPS_S = [30, 60, 120, 300, 600, 900, 1800, 3600];
const AXIS_LABELS = 8;
/** Tooltips of markers past this fraction of the timeline (from either end) open inward, so they never leave the page. */
const TIP_EDGE = 0.8;

const pct = (t: number, duration: number): string => `${(Math.min(Math.max(t / duration, 0), 1) * 100).toFixed(3)}%`;
const sceneName = (index: number): string => `Scene ${String(index + 1).padStart(2, "0")}`;

/** Scenes as a strip, one mark per candidate pause on the rail below, and the playhead. */
export function Timeline({ duration, scenes, candidates, selected, visible, onToggle, onSelect, onSeek, getTime }: Props) {
  const track = useRef<HTMLDivElement>(null);
  const marks = useRef(new Map<number, HTMLButtonElement>());

  const shown = useMemo(() => candidates.filter((c) => visible.has(c.status)), [candidates, visible]);
  const counts = useMemo(() => {
    const n = new Map<CandidateStatus, number>();
    candidates.forEach((c) => n.set(c.status, (n.get(c.status) ?? 0) + 1));
    return n;
  }, [candidates]);
  const axis = useMemo(() => {
    const step = AXIS_STEPS_S.find((s) => duration / s <= AXIS_LABELS) ?? AXIS_STEPS_S[AXIS_STEPS_S.length - 1];
    return Array.from({ length: Math.floor(duration / step) }, (_, i) => (i + 1) * step).filter((t) => t < duration - step / 3);
  }, [duration]);

  useEffect(() => {
    let frame = 0;
    let last = -1;
    const tick = () => {
      const t = getTime();
      if (t !== last && track.current) {
        last = t;
        track.current.style.setProperty("--progress", String(Math.min(t / duration, 1)));
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [getTime, duration]);

  const seekFromPointer = (e: PointerEvent<HTMLDivElement>) => {
    const box = track.current?.getBoundingClientRect();
    if (!box || e.target !== e.currentTarget) return;
    onSeek(Math.min(Math.max((e.clientX - box.left) / box.width, 0), 1) * duration);
  };

  const step = (e: KeyboardEvent, by: -1 | 1) => {
    const i = shown.findIndex((c) => c.t === selected);
    const next = shown[Math.min(Math.max(i + by, 0), shown.length - 1)];
    if (!next) return;
    e.preventDefault();
    onSelect(next.t);
    marks.current.get(next.t)?.focus();
  };

  return (
    <section className="timeline" aria-label="Decision Trace timeline">
      <div
        ref={track}
        className="tl-track"
        onPointerDown={seekFromPointer}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") step(e, 1);
          if (e.key === "ArrowLeft") step(e, -1);
        }}
      >
        <div className="tl-scenes" aria-hidden>
          {scenes.map((s) => (
            <div
              key={s.index}
              className="tl-scene"
              data-unknown={s.unknown}
              data-flagged={s.safety_tags.length > 0}
              style={{ left: pct(s.start, duration), width: `${(((s.end - s.start) / duration) * 100).toFixed(3)}%` }}
              title={`${sceneName(s.index)} · ${clock(s.start)}–${clock(s.end)}${s.unknown ? " · unknown, blocks every brand" : ""}`}
            >
              <span className="long">{sceneName(s.index)}</span>
              <span className="short">{String(s.index + 1).padStart(2, "0")}</span>
            </div>
          ))}
        </div>
        <div className="tl-rail" aria-hidden />
        <div className="tl-marks">
          {shown.map((c) => (
            <button
              key={c.t}
              ref={(el) => {
                if (el) marks.current.set(c.t, el);
                else marks.current.delete(c.t);
              }}
              type="button"
              className="tl-mark"
              data-status={c.status}
              data-shape={STATUS[c.status].shape}
              data-selected={c.t === selected}
              data-side={c.t / duration > TIP_EDGE ? "end" : c.t / duration < 1 - TIP_EDGE ? "start" : "mid"}
              style={{ left: pct(c.t, duration) } as CSSProperties}
              data-tip={`${clock(c.t)} · ${STATUS[c.status].label}`}
              aria-label={`${clock(c.t)}, ${STATUS[c.status].label}`}
              aria-pressed={c.t === selected}
              onClick={() => onSelect(c.t)}
            >
              <i aria-hidden />
              {c.t === selected && <span className="tl-mark-time">{clock(c.t)}</span>}
            </button>
          ))}
        </div>
        <div className="tl-axis" aria-hidden>
          {axis.map((t) => (
            <span key={t} style={{ left: pct(t, duration) }}>
              {clock(t)}
            </span>
          ))}
        </div>
        <div className="tl-playhead" aria-hidden />
      </div>

      <div className="tl-legend" role="group" aria-label="Show candidates by outcome">
        {STATUS_ORDER.filter((s) => counts.has(s)).map((s) => (
          <button
            key={s}
            type="button"
            className="chip-toggle"
            data-status={s}
            data-shape={STATUS[s].shape}
            aria-pressed={visible.has(s)}
            title={STATUS[s].meaning}
            onClick={() => onToggle(s)}
          >
            <i className="glyph" aria-hidden />
            {STATUS[s].label}
            <b>{counts.get(s)}</b>
          </button>
        ))}
        <span className="tl-legend-note">
          <i className="tl-swatch" data-kind="flagged" aria-hidden />
          Safety tags
          <i className="tl-swatch" data-kind="unknown" aria-hidden />
          Unknown, blocks every brand
        </span>
      </div>
    </section>
  );
}
