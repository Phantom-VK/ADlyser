// Browser check for the mid-roll player: content -> ad -> resume, seek-past, and play-once.
// Usage: node scripts/e2e.mjs [name]   (e.g. feluda)   (API on :8000 and `npm run dev` on :5173 must be running)
import { mkdirSync } from "node:fs";
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE ?? "http://127.0.0.1:5173";
const video = process.argv[2] ?? "feluda";
const shots = "../data/e2e";
mkdirSync(shots, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: process.env.CHROME ?? "/usr/bin/google-chrome",
  headless: true,
  args: ["--autoplay-policy=no-user-gesture-required", "--no-sandbox"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1000, height: 640 });
page.on("pageerror", (e) => console.log("PAGE ERROR:", e.message));

const failures = [];
const check = (ok, what, detail = "") => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${what} ${detail}`);
  if (!ok) failures.push(what);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const snap = () =>
  page.evaluate(() => {
    const a = window.adlyser;
    const ad = document.querySelector(".player-ad");
    return {
      mode: a.state.mode,
      content: a.player.currentTime(),
      contentPaused: a.player.paused(),
      adShown: ad.dataset.showing === "true",
      adT: ad.currentTime,
      adDur: ad.duration,
      pill: document.querySelector(".ad-overlay")?.textContent ?? "",
    };
  });
const logNow = () => page.evaluate(() => window.adlyser.state.log);

/** Poll until `ad_end_resume` count reaches n; return samples taken during the ad. */
async function waitForAd(n, label) {
  const samples = [];
  const t0 = Date.now();
  let shot = false;
  while (Date.now() - t0 < 60000) {
    const s = await snap();
    if (s.mode === "ad") {
      samples.push({ ...s, wall: Date.now() - t0 });
      if (!shot && s.adT > 2) {
        await page.screenshot({ path: `${shots}/${label}-ad.png` });
        shot = true;
      }
    }
    if ((await logNow()).filter((e) => e.event === "ad_end_resume").length >= n) return samples;
    await sleep(250);
  }
  throw new Error(`timed out waiting for ad #${n}`);
}

await page.goto(`${BASE}/#/watch/${video}`);
await page.waitForFunction("window.adlyser && window.adlyser.player.readyState() >= 1", { timeout: 30000 });
const breaks = await page.evaluate(() => window.adlyser.breaks.map((b) => ({ id: b.id, time: b.time })));
console.log("breaks from VMAP:", JSON.stringify(breaks));
check(breaks.length >= 2, "VMAP parsed into >= 2 breaks");
const [b1, b2] = breaks;

// 1. Natural mid-roll: play up to break 1.
await page.evaluate((t) => { window.adlyser.player.currentTime(t); return window.adlyser.player.play(); }, b1.time - 3);
const s1 = await waitForAd(1, "break1");
let log = await logNow();
const start1 = log.find((e) => e.event === "ad_start" && e.breakId === b1.id);
check(!!start1 && start1.at >= b1.time - 0.1 && start1.at <= b1.time + 0.7, "ad starts at the break time", `(break ${b1.time}s, started at ${start1?.at}s)`);
check(s1.length > 3 && s1.every((s) => s.contentPaused), "content stays paused during the ad", `(${s1.length} samples)`);
check(s1.every((s) => Math.abs(s.content - s1[0].content) < 0.3), "content position frozen during the ad");
check(s1.every((s) => s.adShown) && s1.some((s) => /^AD00:(0\d|10)/.test(s.pill)), "ad overlay with the 'AD mm:ss' countdown shown", `(last pill: ${s1.at(-1)?.pill})`);
const adWall = (s1.at(-1).wall - s1[0].wall) / 1000;
check(adWall > 7 && adWall < 12, "ad plays for about its 10 s duration", `(~${adWall.toFixed(1)}s)`);
await sleep(2000);
const after1 = await snap();
check(after1.mode === "content" && !after1.contentPaused, "content resumes playing after the ad");
check(after1.content >= b1.time - 0.2 && after1.content <= b1.time + 4, "content resumes at the break position", `(now ${after1.content.toFixed(2)}s, break ${b1.time}s)`);

// 2. A break plays once: go back before it and play through again.
const countStarts = async () => (await logNow()).filter((e) => e.event === "ad_start").length;
const startsBefore = await countStarts();
await page.evaluate((t) => { window.adlyser.player.currentTime(t); }, b1.time - 3);
await sleep(5000);
check((await countStarts()) === startsBefore, "an already-played break does not play again");

// 3. Seek past break 2: the ad plays, then content resumes at the seek target.
const target = b2.time + 20;
await page.evaluate((t) => { window.adlyser.player.currentTime(t); }, target);
const s2 = await waitForAd(2, "break2");
log = await logNow();
check(log.some((e) => e.event === "ad_start" && e.breakId === b2.id), "seeking past a break triggers it");
await sleep(2000);
const after2 = await snap();
check(after2.content >= target - 0.5 && after2.content <= target + 5, "after a seek-past ad, content resumes at the seek target", `(target ${target.toFixed(1)}s, now ${after2.content.toFixed(2)}s)`);
check(s2.length > 3, "second ad actually played", `(${s2.length} samples)`);

console.log("event log:", JSON.stringify(log));
await browser.close();
console.log(failures.length ? `\nFAILED: ${failures.length} check(s)` : "\nALL CHECKS PASSED");
process.exit(failures.length ? 1 : 0);
