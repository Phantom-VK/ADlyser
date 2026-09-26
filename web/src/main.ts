import videojs from "video.js";
import "video.js/dist/video-js.css";
import { attachMidrolls } from "./midroll";
import { parseVmap } from "./vmap";

const params = new URLSearchParams(location.search);
const video = params.get("video") ?? "";
const vmapUrl = params.get("vmap") ?? `/data/${video.replace(/\.[^.]+$/, "")}/vmap.xml`;
const status = document.getElementById("status") as HTMLElement;

async function main(): Promise<void> {
  if (!video) {
    status.textContent = "Add ?video=<file.mp4> to the URL.";
    return;
  }
  const player = videojs("content", { sources: [{ src: `/videos/${video}`, type: "video/mp4" }] });
  let breaks: ReturnType<typeof parseVmap> = [];
  try {
    breaks = parseVmap(await (await fetch(vmapUrl)).text());
  } catch (err) {
    status.textContent = `No usable VMAP (${String(err)}); playing without ads.`;
  }
  const state = attachMidrolls(
    player,
    document.getElementById("ad") as HTMLVideoElement,
    document.getElementById("pill") as HTMLElement,
    breaks,
  );
  status.textContent = `${breaks.length} ad break(s) from ${vmapUrl}`;
  Object.assign(window, { adlyser: { player, breaks, state } });
}

void main();
