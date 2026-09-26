import type { ReactNode } from "react";
import { tagLabel } from "../lib/format";

/** A technical label: small, uppercase, tracked out. */
export function Label({ children, as: Tag = "p" }: { children: ReactNode; as?: "p" | "h2" | "h3" | "h4" | "span" }) {
  return <Tag className="label">{children}</Tag>;
}

/** Compact technical tags. `tone` colours only the tags: danger for a blocking tag, warn for a review flag. */
export function Tags({ tags, tone = "neutral", empty }: { tags: string[]; tone?: "neutral" | "danger" | "warn" | "accent"; empty?: string }) {
  if (tags.length === 0) return empty ? <span className="muted">{empty}</span> : null;
  return (
    <span className="tags">
      {tags.map((t) => (
        <span key={t} className="tag" data-tone={tone}>
          {tagLabel(t)}
        </span>
      ))}
    </span>
  );
}

/** A 0..1 score as a number over a thin bar. */
export function Score({ value, label }: { value: number; label: string }) {
  const v = Math.min(Math.max(value, 0), 1);
  return (
    <span className="score" role="img" aria-label={`${label} ${v.toFixed(2)}`}>
      <b>{v.toFixed(2)}</b>
      <span className="score-bar">
        <i style={{ width: `${(v * 100).toFixed(0)}%` }} />
      </span>
    </span>
  );
}

/** A pass or fail mark for a check. */
export function Check({ ok }: { ok: boolean }) {
  return (
    <span className="check" data-ok={ok} role="img" aria-label={ok ? "pass" : "fail"}>
      {ok ? "✓" : "✕"}
    </span>
  );
}

/** A 16:9 frame from the video that reserves its space while it loads. */
export function Thumb({ src, alt }: { src: string; alt: string }) {
  return (
    <div className="thumb">
      <img src={src} alt={alt} width={640} height={360} loading="lazy" decoding="async" />
    </div>
  );
}
