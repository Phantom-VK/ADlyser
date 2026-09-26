// Browser check, in two parts.
//  1. The flow: home -> click a sample -> ready screen -> Analyse -> processing dialog -> analysis page -> Home
//     (the video is now in "Recently analysed" and gone from the samples).
//  2. The mid-roll player: content -> ad -> resume, seek-past, and play-once.
// Usage: node scripts/e2e.mjs [name]   (a sample that is NOT analysed yet, and whose model calls are cached, e.g. mohanagar, which has 2 breaks)
// The API and `npm run dev` must be running (BASE defaults to :5173). To spend nothing, point the API at a scratch data
// folder and an existing cache:  ADLYSER_DATA_DIR=data/e2e_run ADLYSER_CACHE_DIR=data/cache.eval uv run uvicorn adlyser.api:app --port 8001
// and  API=http://127.0.0.1:8001 npx vite --port 5174,  then  BASE=http://127.0.0.1:5174 node scripts/e2e.mjs
import { mkdirSync } from "node:fs";
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE ?? "http://127.0.0.1:5173";
const video = process.argv[2] ?? "mohanagar";
const shots = "../data/e2e";
mkdirSync(shots, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: process.env.CHROME ?? "/usr/bin/google-chrome",
  headless: true,
  args: ["--autoplay-policy=no-user-gesture-required", "--no-sandbox"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900 });
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

// ---- Part 1: the flow ----------------------------------------------------------------------------------
const cardTitles = (section) =>
  page.$$eval(`section[aria-labelledby="${section}"] .card-title`, (els) => els.map((e) => e.textContent.trim().toLowerCase()));
const label = video.replace(/[-_]/g, " ").toLowerCase();

await page.goto(`${BASE}/#/`, { waitUntil: "networkidle2" });
await page.waitForSelector(".dropbox");
const dropText = await page.$eval(".dropbox", (e) => e.textContent);
check(/MB/.test(dropText) && /\.mp4/.test(dropText) && !!(await page.$(".dropbox .btn-primary")), "home: an upload box with the size limit and a Choose file button", `(${dropText.replace(/\s+/g, " ").slice(0, 90)})`);
await page.waitForSelector("#samples");
const samplesBefore = await cardTitles("samples");
check(samplesBefore.includes(label), "home: the sample is in the sample grid", `(${samplesBefore.join(", ")})`);
check(!(await page.$("#recent")) || !(await cardTitles("recent")).includes(label), "home: it is not in Recently analysed yet");
await page.waitForFunction(() => [...document.querySelectorAll(".card img")].every((i) => i.complete), { timeout: 30000 });
await page.screenshot({ path: `${shots}/home-before.png` });

await page.$$eval('section[aria-labelledby="samples"] .card', (els, l) => els.find((e) => e.textContent.toLowerCase().includes(l)).click(), label);
await page.waitForFunction(() => location.hash === "#/prepare");
await page.waitForSelector(".prepare-video");
await page.waitForFunction(() => !/…/.test(document.querySelector(".facts")?.textContent ?? "…"), { timeout: 20000 });
const facts = await page.$eval(".facts", (e) => e.textContent.replace(/\s+/g, " "));
check(facts.includes(`${video}.mp4`) && /\d+:\d\d/.test(facts) && /MB/.test(facts), "ready screen: file name, duration and size", `(${facts})`);
check(!!(await page.$(".prepare .btn-primary")) && (await page.$eval(".prepare .btn-secondary", (e) => e.textContent)) === "Back", "ready screen: Analyse and Back buttons");
const idle = await (await fetch(`${BASE}/api/jobs/${video}`)).json();
check(idle.status === "idle", "nothing has started before Analyse is pressed", `(job ${idle.status})`);
await page.screenshot({ path: `${shots}/ready.png` });

// Cached runs finish in seconds, so record every state the dialog passes through, and deliver progress events at
// a walking pace (a test hook on EventSource only) so a screenshot can catch the dialog mid-run.
await page.evaluate(() => {
  window.__seen = { running: [], details: [], pcts: [] };
  const note = (list, v) => v && list.at(-1) !== v && list.push(v);
  new MutationObserver(() => {
    const d = document.querySelector('[role="dialog"].run');
    if (!d) return;
    note(window.__seen.running, d.querySelector('[data-state="running"] span')?.textContent);
    note(window.__seen.details, d.querySelector(".run-detail")?.textContent);
    window.__seen.pcts.push(Number(d.querySelector('[role="progressbar"]').getAttribute("aria-valuenow")));
  }).observe(document.body, { subtree: true, childList: true, attributes: true, characterData: true });
  const Native = window.EventSource;
  let n = 0;
  window.EventSource = class extends Native {
    set onmessage(fn) { super.onmessage = fn ? (e) => setTimeout(() => fn(e), ++n * 60) : null; }
    set onerror(fn) { super.onerror = fn ? (e) => setTimeout(() => fn(e), ++n * 60) : null; }
  };
});
await page.click(".prepare .btn-primary");
await page.waitForSelector('[role="dialog"].run');
const dlg = await page.$eval('[role="dialog"]', (e) => ({ modal: e.getAttribute("aria-modal"), inside: e.contains(document.activeElement) || document.activeElement === e, steps: e.querySelectorAll(".run-steps li").length, bar: !!e.querySelector('[role="progressbar"]'), inert: document.getElementById("root").hasAttribute("inert") }));
check(dlg.modal === "true" && dlg.inside && dlg.bar && dlg.inert, "dialog: modal, focus inside, page behind inert, progress bar", JSON.stringify(dlg));
check(dlg.steps === 10, "dialog: ten steps listed", `(${dlg.steps})`);
await page.keyboard.press("Escape");
await page.keyboard.press("Tab");
await page.mouse.click(5, 5);
const stillOpen = await page.evaluate(() => !!document.querySelector('[role="dialog"].run') && location.hash === "#/prepare" || location.hash.startsWith("#/video/"));
const focusKept = await page.evaluate(() => !document.querySelector('[role="dialog"].run') || document.querySelector('[role="dialog"].run').contains(document.activeElement));
check(stillOpen && focusKept, "dialog: Esc, a backdrop click and Tab do not close it or leave it");

let shotProgress = false;
const t0 = Date.now();
while (!(await page.evaluate(() => location.hash.startsWith("#/video/")))) {
  if (Date.now() - t0 > 240000) throw new Error("timed out in the processing dialog");
  const s = await page.evaluate(() => {
    const d = document.querySelector('[role="dialog"].run');
    return d && { done: d.querySelectorAll('[data-state="done"]').length, detail: d.querySelector(".run-detail")?.textContent ?? "", error: d.querySelector(".alert")?.textContent ?? null };
  });
  if (s?.error) throw new Error(`the dialog reported an error: ${s.error}`);
  if (!shotProgress && s && s.done >= 3 && /\d+ of \d+/.test(s.detail)) { await page.screenshot({ path: `${shots}/dialog.png` }); shotProgress = true; }
  await sleep(50);
}
const seen = await page.evaluate(() => window.__seen);
console.log(`steps seen running: ${seen.running.join(" > ")}`);
console.log(`detail lines seen: ${seen.details.slice(0, 8).join(" | ")}${seen.details.length > 8 ? " ..." : ""}`);
check(seen.running.length >= 6, "dialog: steps moved from pending to running to done in order", `(${seen.running.length} distinct running steps)`);
check(seen.details.some((d) => /\d+ of \d+/.test(d)), "dialog: a detail line such as 'Analysing stretch 7 of 20'");
check(seen.pcts.every((v, i) => i === 0 || v >= seen.pcts[i - 1]), "dialog: the overall progress never went backwards", `(${seen.pcts[0]}% -> ${seen.pcts.at(-1)}%)`);
check(shotProgress, "a screenshot of the dialog mid-run was taken");
await page.waitForSelector(".tl-mark", { timeout: 30000 });
check((await page.$('[role="dialog"]')) === null && !(await page.evaluate(() => document.getElementById("root").hasAttribute("inert"))), "the dialog closed on its own and the page is usable again");
check(await page.evaluate((v) => location.hash.startsWith(`#/video/${v}`), video), "landed on the analysis page", `(${await page.evaluate(() => location.hash)})`);

await page.click(".wordmark");
await page.waitForFunction(() => location.hash === "#/");
await page.waitForSelector("#recent");
const recent = await cardTitles("recent");
const samplesAfter = (await page.$("#samples")) ? await cardTitles("samples") : [];
check(recent[0] === label, "home: the video is first in Recently analysed", `(${recent.join(", ")})`);
check(!samplesAfter.includes(label), "home: and gone from the sample grid", `(${samplesAfter.join(", ") || "none left"})`);
await page.waitForFunction(() => [...document.querySelectorAll(".card img")].every((i) => i.complete), { timeout: 30000 });
await page.screenshot({ path: `${shots}/home-after.png` });

// ---- Part 2: the mid-roll player ------------------------------------------------------------------------
await page.goto(`${BASE}/#/video/${video}`);
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

// ---- Part 3: a failed run never leaves the person stuck ---------------------------------------------------
const bad = await browser.newPage();
await bad.setViewport({ width: 1440, height: 900 });
await bad.setRequestInterception(true);
bad.on("request", (r) => (r.url().includes("/run") && r.method() === "POST" ? r.respond({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: "another job is running" }) }) : r.continue()));
await bad.goto(`${BASE}/#/`, { waitUntil: "networkidle2" });
await bad.$$eval('section[aria-labelledby="samples"] .card', (els) => els[0].click());
await bad.waitForSelector(".prepare .btn-primary");
await bad.click(".prepare .btn-primary");
await bad.waitForSelector('[role="dialog"] .alert');
await sleep(200);
const failure = await bad.evaluate(() => ({ text: document.querySelector('[role="dialog"] .alert').textContent, focus: document.activeElement.textContent }));
check(/another job is running/.test(failure.text) && failure.focus === "Back to home", "error: the message is shown and focus is on Back to home", JSON.stringify(failure));
await bad.screenshot({ path: `${shots}/dialog-error.png` });
await bad.keyboard.press("Enter");
await bad.waitForFunction(() => location.hash === "#/");
await sleep(400);
check(await bad.evaluate(() => !document.querySelector('[role="dialog"]') && !document.getElementById("root").hasAttribute("inert")), "error: Back to home closes the dialog and frees the page");
await bad.close();

console.log("event log:", JSON.stringify(log));
await browser.close();
console.log(failures.length ? `\nFAILED: ${failures.length} check(s)` : "\nALL CHECKS PASSED");
process.exit(failures.length ? 1 : 0);
