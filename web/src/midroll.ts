/** VMAP-driven mid-roll insertion: pause content, play the ad, resume at the exact timestamp. */
import type videojs from "video.js";
import type { AdBreak } from "./vmap";

export interface MidrollState {
  mode: "content" | "ad";
  /** What happened, in order, for debugging and browser checks. */
  log: { event: string; at: number; breakId?: string }[];
}

type Player = ReturnType<typeof videojs>;

const NATURAL_WINDOW_S = 1.0;

const clock = (s: number): string => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/**
 * Attach mid-roll behaviour to a content player.
 * - Reaching a break during normal playback plays its ad, then resumes at the break time.
 * - Seeking past unplayed breaks plays the latest one, then resumes at the seek target.
 * - A break plays once. An ad that fails to load is skipped and content resumes.
 */
export function attachMidrolls(
  player: Player,
  adEl: HTMLVideoElement,
  pill: HTMLElement,
  breaks: AdBreak[],
): MidrollState {
  const state: MidrollState = { mode: "content", log: [] };
  let resumeAt = 0;

  const note = (event: string, breakId?: string) =>
    state.log.push({ event, at: Number((player.currentTime() ?? 0).toFixed(2)), breakId });

  const finishAd = (event: string) => {
    if (state.mode !== "ad") return;
    state.mode = "content";
    adEl.pause();
    adEl.style.display = "none";
    pill.style.display = "none";
    player.currentTime(resumeAt);
    void player.play();
    note(event);
  };

  const playAd = (due: AdBreak, resume: number) => {
    state.mode = "ad";
    resumeAt = resume;
    player.pause();
    note("ad_start", due.id);
    adEl.src = due.ad.url;
    adEl.style.display = "block";
    pill.style.display = "block";
    pill.textContent = `Ad · ${clock(due.ad.duration)}`;
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

  adEl.addEventListener("timeupdate", () => {
    const left = Math.max(0, (adEl.duration || 0) - adEl.currentTime);
    pill.textContent = `Ad · ${clock(left)}`;
  });
  adEl.addEventListener("ended", () => finishAd("ad_end_resume"));
  adEl.addEventListener("error", () => finishAd("ad_error_resume"));

  player.on("timeupdate", check);
  player.on("seeked", check);
  const tick = () => {
    if (!player.paused()) check();
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);

  return state;
}
