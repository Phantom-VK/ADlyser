import videojs from "video.js";
import "video.js/dist/video-js.css";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { countdown } from "../lib/format";
import { attachMidrolls, type MidrollState } from "../lib/midroll";
import type { AdBreak } from "../lib/vmap";
import { clock } from "../lib/format";

type VjsPlayer = ReturnType<typeof videojs>;

/** What the page can do with the player. */
export interface PlayerHandle {
  /** Jump to a time. Content plays from there if it was playing. */
  seek: (t: number) => void;
  /** The content position in seconds (ignores the ad). */
  time: () => number;
}

interface Props {
  videoUrl: string;
  breaks: AdBreak[];
}

interface AdView {
  title: string;
  left: number;
  progress: number;
  resumeAt: number;
}

/** The content video with VMAP mid-rolls: it pauses at each break, plays the ad and resumes. */
export const Player = forwardRef<PlayerHandle, Props>(function Player({ videoUrl, breaks }, ref) {
  const mount = useRef<HTMLDivElement>(null);
  const adEl = useRef<HTMLVideoElement>(null);
  const player = useRef<VjsPlayer | null>(null);
  const [ready, setReady] = useState(0);
  const [ad, setAd] = useState<AdView | null>(null);

  useImperativeHandle(ref, () => ({
    seek: (t) => player.current?.currentTime(t),
    time: () => player.current?.currentTime() ?? 0,
  }));

  useEffect(() => {
    if (!mount.current) return;
    const el = document.createElement("video");
    el.className = "video-js";
    el.setAttribute("playsinline", "");
    mount.current.appendChild(el);
    const p = videojs(el, {
      controls: true,
      preload: "auto",
      fluid: true,
      aspectRatio: "16:9",
      playbackRates: [0.5, 1, 1.5, 2],
      sources: [{ src: videoUrl, type: "video/mp4" }],
    });
    player.current = p;
    setReady((n) => n + 1);
    return () => {
      player.current = null;
      p.dispose();
    };
  }, [videoUrl]);

  useEffect(() => {
    const p = player.current;
    const el = adEl.current;
    if (!p || !el) return;
    const view = (s: MidrollState): AdView | null =>
      s.mode === "ad" && s.current
        ? { title: s.current.ad.title, left: s.current.ad.duration, progress: 0, resumeAt: s.current.time }
        : null;
    const onChange = (s: MidrollState) => setAd(view(s));
    const { state, dispose } = attachMidrolls(p, el, breaks, onChange);
    const onTime = () =>
      setAd((cur) => {
        if (!cur || !el.duration) return cur;
        return { ...cur, left: el.duration - el.currentTime, progress: el.currentTime / el.duration };
      });
    el.addEventListener("timeupdate", onTime);
    Object.assign(window, { adlyser: { player: p, breaks, state } });
    return () => {
      el.removeEventListener("timeupdate", onTime);
      dispose();
      setAd(null);
    };
  }, [breaks, ready]);

  return (
    <div className="player">
      <div ref={mount} className="player-content" />
      <video ref={adEl} className="player-ad" playsInline data-showing={ad !== null} />
      <div className="ad-overlay" data-showing={ad !== null} role="status" aria-live="polite">
        {ad && (
          <>
            <div className="ad-strip">
              <span className="ad-tag">AD</span>
              <span className="ad-time">{countdown(ad.left)}</span>
              <span className="ad-title">{ad.title}</span>
              <span className="ad-resume">Story resumes at {clock(ad.resumeAt)}</span>
            </div>
            <div className="ad-progress" style={{ transform: `scaleX(${ad.progress})` }} />
          </>
        )}
      </div>
    </div>
  );
});
