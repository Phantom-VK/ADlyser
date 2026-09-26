// Browser check for the whole flow with a real run: upload -> live pipeline -> results -> add a brand -> re-match.
// Usage: node scripts/e2e-flow.mjs <clip.mp4>   (API on :8000 and `npm run dev` on :5173 must be running; makes paid API calls unless cached)
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE ?? "http://127.0.0.1:5173";
const clip = process.argv[2];
const shots = process.env.SHOTS ?? "/tmp";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const failures = [];
const check = (ok, what, detail = "") => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${what} ${detail}`);
  if (!ok) failures.push(what);
};
const click = (page, selector) => page.$eval(selector, (el) => el.click());
const state = (page) => page.$eval(".pipeline-state", (e) => e.textContent);

const browser = await puppeteer.launch({ executablePath: process.env.CHROME ?? "/usr/bin/google-chrome", headless: true, args: ["--no-sandbox"] });
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 1000 });
page.on("pageerror", (e) => check(false, "no page errors", e.message));

await page.goto(`${BASE}/#/`, { waitUntil: "networkidle2" });
await (await page.$('input[type="file"]')).uploadFile(clip);
await page.waitForFunction(() => location.hash.startsWith("#/watch/"), { timeout: 60000 });
const name = await page.evaluate(() => location.hash.split("?")[0].split("/").pop());
check(true, "upload started the analysis and opened its page", `(${name})`);

await page.waitForSelector(".pipeline");
const seen = new Set();
const t0 = Date.now();
let shot = false;
while (Date.now() - t0 < 900000) {
  const s = await page.evaluate(() => ({
    title: document.querySelector(".pipeline-state")?.textContent,
    done: document.querySelectorAll('.stage[data-state="done"]').length,
    active: document.querySelector('.stage[data-state="active"] .stage-label')?.textContent ?? null,
  }));
  if (s.active) seen.add(s.active);
  if (!shot && s.done >= 2) { await page.screenshot({ path: `${shots}/flow-progress.png` }); shot = true; }
  if (s.title === "Complete" || s.title === "Failed") { check(s.title === "Complete", "pipeline finished", `(${Math.round((Date.now() - t0) / 1000)} s, stages seen running: ${[...seen].join(", ")})`); break; }
  await sleep(400);
}
await page.waitForSelector(".tl-mark", { timeout: 30000 });
const report = await (await fetch(`${BASE}/data/${name}/debug.json`)).json();
const vmap = await (await fetch(`${BASE}/data/${name}/vmap.xml`)).text();
check((await page.$$(".tl-mark")).length === report.candidates.length, "results loaded: a marker per candidate", `(${report.candidates.length} candidates, ${report.breaks.filter((b) => b.outcome !== "dropped").length} breaks)`);
await page.screenshot({ path: `${shots}/flow-results.png`, fullPage: true });

// Add a brand with the form: normalize, then re-match.
await page.type('input[name="brand-name"]', "Lotus Lassi");
await page.type('input[name="brand-category"]', "Beverage");
await page.type('input[name="brand-targets"]', "Summer scenes, family get-togethers");
await page.type('input[name="brand-negatives"]', "Funerals, hospital scenes, illness");
await click(page, ".add-brand .btn-secondary");
await page.waitForSelector(".normalised", { timeout: 60000 });
const normalised = await page.$eval(".normalised", (e) => e.textContent);
check(/Brand normalized/.test(normalised) && /Lotus Lassi/.test(normalised) && /medical illness|death grief|funeral ritual/i.test(normalised), "the form was normalized into a brand with negative tags", `(${normalised.replace(/\s+/g, " ").slice(0, 110)}…)`);
await page.screenshot({ path: `${shots}/flow-normalised.png` });
const r0 = Date.now();
await click(page, ".normalised .btn-primary");
await page.waitForFunction(() => document.querySelector(".pipeline-state")?.textContent === "Running" || document.querySelector(".pipeline-state")?.textContent === "Complete", { timeout: 30000 });
await page.waitForFunction(() => document.querySelector(".pipeline-state")?.textContent === "Complete", { timeout: 600000 });
check(true, "re-match finished", `(${Math.round((Date.now() - r0) / 1000)} s)`);
await page.waitForSelector(".rematch", { timeout: 20000 });
const summary = await page.$eval(".rematch", (e) => e.textContent.replace(/\s+/g, " "));
check(/Scene intelligence\s*Cached/i.test(summary) && /Brand matching\s*Updated/i.test(summary), "the summary says no video was re-analysed", `(${summary})`);
const after = await (await fetch(`${BASE}/data/${name}/debug.json`)).json();
check(after.brands.some((b) => b.name === "Lotus Lassi"), "the new brand is in the catalogue used by the new run", `(${report.brands.length} -> ${after.brands.length} brands)`);
const rows = await page.$$eval(".brand-table .brand-name", (els) => els.map((e) => e.textContent));
check(rows.includes("Lotus Lassi"), "the brands table lists it");
const same = vmap === (await (await fetch(`${BASE}/data/${name}/vmap.xml`)).text());
console.log(`manifest ${same ? "unchanged" : "changed"} by the new brand`);
await page.screenshot({ path: `${shots}/flow-rematched.png`, fullPage: true });

await browser.close();
console.log(failures.length ? `\nFAILED: ${failures.length} check(s)` : "\nALL CHECKS PASSED");
console.log(`job folder: data/${name}`);
process.exit(failures.length ? 1 : 0);
