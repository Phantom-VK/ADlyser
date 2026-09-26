/** Small formatting helpers shared by the pages. */

/** Seconds as `m:ss`, or `h:mm:ss` from one hour. */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

/** `indubala_bhaater_hotel` as `Indubala Bhaater Hotel`. */
export function titleOf(name: string): string {
  return name.replace(/[-_]+/g, " ").replace(/\b\p{L}/gu, (c) => c.toUpperCase());
}

/** `death_grief` as `death grief`. */
export const tagLabel = (tag: string): string => tag.replace(/_/g, " ");

/** Minutes with one decimal, for durations: `25.6 min`. */
export const minutes = (seconds: number): string => `${(seconds / 60).toFixed(1)} min`;

/** A time range as `7:26–8:10`. */
export const range = (start: number, end: number): string => `${clock(start)}–${clock(end)}`;

const pad = (n: number, width = 2): string => String(n).padStart(width, "0");

/** A precise timecode, `hh:mm:ss.mmm`, as used in the manifest. */
export function precise(seconds: number): string {
  const ms = Math.round(Math.max(0, seconds) * 1000);
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  const s = Math.floor((ms % 60_000) / 1000);
  return `${pad(h)}:${pad(m)}:${pad(s)}.${pad(ms % 1000, 3)}`;
}

/** `mm:ss`, both padded: the ad countdown. */
export const countdown = (seconds: number): string => {
  const s = Math.max(0, Math.ceil(seconds));
  return `${pad(Math.floor(s / 60))}:${pad(s % 60)}`;
};

/** A plural label: `2 breaks`. */
export const count = (n: number, one: string, many = `${one}s`): string => `${n} ${n === 1 ? one : many}`;

/** A file size in the unit a person reads: `48 MB`, `1.2 GB`. */
export const bytes = (n: number): string => {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} GB`;
  if (n >= 1024 ** 2) return `${Math.round(n / 1024 ** 2)} MB`;
  return `${Math.max(Math.round(n / 1024), 1)} KB`;
};

/** When something happened, from seconds since the epoch: `26 Sep, 19:45`. */
export const when = (epochSeconds: number): string =>
  new Date(epochSeconds * 1000).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
