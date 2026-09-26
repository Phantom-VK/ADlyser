/** Parse a VMAP 1.0 document (inline VAST linear ads) into a list of breaks. */

export interface AdBreak {
  id: string;
  /** Seconds into the content where the break plays. */
  time: number;
  ad: { title: string; duration: number; url: string };
  played: boolean;
}

/** `hh:mm:ss(.mmm)` to seconds. Returns NaN for anything else. */
export function parseOffset(text: string): number {
  const m = /^(\d+):(\d{2}):(\d{2})(?:\.(\d{1,3}))?$/.exec(text.trim());
  if (!m) return Number.NaN;
  const ms = m[4] ? Number(m[4].padEnd(3, "0")) : 0;
  return Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]) + ms / 1000;
}

const text = (root: Element, name: string): string =>
  root.getElementsByTagNameNS("*", name)[0]?.textContent?.trim() ?? "";

/** Breaks in ascending time order. Breaks without a usable offset or media file are skipped. */
export function parseVmap(xml: string): AdBreak[] {
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  if (doc.getElementsByTagName("parsererror").length > 0) throw new Error("VMAP is not valid XML");
  const breaks: AdBreak[] = [];
  for (const el of Array.from(doc.getElementsByTagNameNS("*", "AdBreak"))) {
    const time = parseOffset(el.getAttribute("timeOffset") ?? "");
    const url = text(el, "MediaFile");
    if (Number.isNaN(time) || !url) continue;
    breaks.push({
      id: el.getAttribute("breakId") ?? `break-${breaks.length + 1}`,
      time,
      ad: { title: text(el, "AdTitle"), duration: parseOffset(text(el, "Duration")) || 0, url },
      played: false,
    });
  }
  return breaks.sort((a, b) => a.time - b.time);
}
