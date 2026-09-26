/** VMAP-driven mid-roll insertion: pause content, play the ad, resume at the exact timestamp. */
import type videojs from "video.js";
import type { AdBreak } from "./vmap";

export interface MidrollState {
  mode: "content" | "ad";
  /** The break whose ad is playing, while `mode` is "ad". */
  current: AdBreak | null;
  /** What happened, in order, for debugging and browser checks. */
  log: { event: string; at: number; breakId?: string }[];
}

type Player = ReturnType<typeof videojs>;

/** Reaching a break within this many seconds of its time counts as a natural mid-roll, not a seek-past. */
const NATURAL_WINDOW_S = 1.0;

/**
 * Attach mid-roll behaviour to a content player.
 * - Reaching a break during normal playback plays its ad, then resumes at the break time.
 * - Seeking past unplayed breaks plays the latest one, then resumes at the seek target.
 * - A break plays once. An ad that fails to load is skipped and content resumes.
 * - Breaks at or before the current position when attached count as already played.
 *
 * @param onChange called whenever `mode` or `current` changes, so the page can show the ad state.
 * @returns the live state and a function that removes every listener.
 */
export function attachMidrolls(
  player: Player,
  adEl: HTMLVideoElement,
  breaks: AdBreak[],
  onChange: (state: MidrollState) => void = () => {},
): { state: MidrollState; dispose: () => void } {
  const state: MidrollState = { mode: "content", current: null, log: [] };
  const listeners = new AbortController();
  let resumeAt = 0;
  let frame = 0;

  const start = player.currentTime() ?? 0;
  if (start > 0) breaks.forEach((b) => (b.played = b.time <= start));

  const note = (event: string, breakId?: string) =>
    state.log.push({ event, at: Number((player.currentTime() ?? 0).toFixed(2)), breakId });

  const finishAd = (event: string) => {
    if (state.mode !== "ad") return;
    state.mode = "content";
    state.current = null;
    adEl.pause();
    player.currentTime(resumeAt);
    void player.play();
    note(event);
    onChange(state);
  };

  const playAd = (due: AdBreak, resume: number) => {
    state.mode = "ad";
    state.current = due;
    resumeAt = resume;
    player.pause();
    note("ad_start", due.id);
    adEl.src = due.ad.url;
    onChange(state);
    adEl.play().catch(() => finishAd("ad_blocked_resume"));
  };

  const check = () => {
    if (state.mode !== "content") return;
    const t = player.currentTime() ?? 0;
    const due = breaks.filter((b) => !b.played && b.time <= t);
    if (due.length === 0) return;
    due.forEach((b) => (b.played = true));
    const latest = due[due.length - 1];
    playAd(latest, t - latest.time <= NATURAL_WINDOW_S ? latest.time : t);
  };

  const opts = { signal: listeners.signal };
  adEl.addEventListener("ended", () => finishAd("ad_end_resume"), opts);
  adEl.addEventListener("error", () => finishAd("ad_error_resume"), opts);
  player.on("timeupdate", check);
  player.on("seeked", check);
  const tick = () => {
    if (!player.paused()) check();
    frame = requestAnimationFrame(tick);
  };
  frame = requestAnimationFrame(tick);

  const dispose = () => {
    cancelAnimationFrame(frame);
    listeners.abort();
    player.off("timeupdate", check);
    player.off("seeked", check);
    adEl.pause();
  };
  return { state, dispose };
}
