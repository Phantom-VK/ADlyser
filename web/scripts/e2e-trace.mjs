// Browser check for the Decision Trace: every candidate opens with its reason, blocked ones show the blocking tags.
// Usage: node scripts/e2e-trace.mjs [name]   (API on :8000 and `npm run dev` on :5173 must be running)
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE ?? "http://127.0.0.1:5173";
const name = process.argv[2] ?? "feluda";
const report = await (await fetch(`${BASE}/data/${name}/debug.json`)).json();

const browser = await puppeteer.launch({ executablePath: process.env.CHROME ?? "/usr/bin/google-chrome", headless: true, args: ["--no-sandbox"] });
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 1000 });
const failures = [];
const check = (ok, what, detail = "") => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${what} ${detail}`);
  if (!ok) failures.push(what);
};
page.on("pageerror", (e) => check(false, "no page errors", e.message));

await page.goto(`${BASE}/#/watch/${name}`, { waitUntil: "networkidle2" });
await page.waitForSelector(".tl-mark");
const marks = () => page.$$eval(".tl-mark", (els) => els.map((e) => ({ label: e.getAttribute("aria-label"), status: e.dataset.status })));
const all = await marks();
check(all.length === report.candidates.length, "one mark per candidate", `(${all.length} of ${report.candidates.length})`);
const statuses = new Set(report.candidates.map((c) => c.status));
console.log("statuses in this episode:", [...statuses].join(", "));

const pad = (n, w = 2) => String(n).padStart(w, "0");
const clock = (s) => { const ms = Math.round(s * 1000); return `${pad(Math.floor(ms / 3600000))}:${pad(Math.floor((ms % 3600000) / 60000))}:${pad(Math.floor((ms % 60000) / 1000))}.${pad(ms % 1000, 3)}`; };
let opened = 0;
for (const [i, c] of report.candidates.entries()) {
  const handle = (await page.$$(".tl-mark"))[i];
  await handle.evaluate((el) => el.click());
  await page.waitForFunction((t) => document.querySelector(".trace-time")?.textContent === t, {}, clock(c.t));
  const panel = await page.evaluate(() => ({
    why: document.querySelector(".trace")?.textContent ?? "",
    status: document.querySelector(".trace .status")?.textContent ?? "",
    blocked: [...document.querySelectorAll(".match-row[data-blocked]")].map((li) => ({ name: li.querySelector(".match-name")?.textContent, tags: li.querySelectorAll(".tag").length })),
    reviewer: /reviewer/i.test(document.body.innerText),
  }));
  const rec = report.breaks.find((b) => b.t === c.t);
  const ok =
    panel.why.includes(c.boundary_reason.slice(0, 30)) &&
    panel.status.length > 0 &&
    (!rec || rec.blocked.length === panel.blocked.length) &&
    panel.blocked.every((b) => b.tags > 0) &&
    (!c.review || panel.reviewer);
  check(ok, `${clock(c.t)} ${c.status} opens with its reason`, rec ? `(${panel.blocked.length} blocked brands with tags)` : "");
  opened += ok ? 1 : 0;
}
check(opened === report.candidates.length, "every candidate opens");

// A blocked candidate that has brand records shows the exact blocking tags, and which side.
const blockedRec = report.breaks.find((b) => b.blocked.length > 0);
if (blockedRec) {
  const i = report.candidates.findIndex((c) => c.t === blockedRec.t);
  await (await page.$$(".tl-mark"))[i].evaluate((el) => el.click());
  await page.waitForFunction((t) => document.querySelector(".trace-time")?.textContent === t, {}, clock(blockedRec.t));
  const text = await page.$eval(".match", (el) => el.textContent);
  const first = blockedRec.blocked[0];
  check(text.includes(first.name) && first.tags.every((t) => text.includes(t.replace(/_/g, " "))), "blocked brands list their exact blocking tags", `(${first.name}: ${first.tags.join(", ")})`);
}

// Filter chips hide and show marks.
const chip = await page.$('.chip-toggle[data-status="not_scene_change"]');
if (chip) {
  const before = (await marks()).length;
  await chip.evaluate((el) => el.click());
  const after = (await marks()).length;
  check(after < before, "a status chip hides its marks", `(${before} → ${after})`);
  await chip.evaluate((el) => el.click());
  check((await marks()).length === before, "and shows them again");
}

// Keyboard: arrows move the selection.
await (await page.$$(".tl-mark"))[0].focus();
await page.keyboard.press("Enter");
const t0 = await page.$eval(".trace-time", (e) => e.textContent);
await page.keyboard.press("ArrowRight");
await page.waitForFunction((prev) => document.querySelector(".trace-time")?.textContent !== prev, {}, t0);
check(true, "ArrowRight moves to the next candidate");

// The breaks list selects the same trace.
const first = report.breaks.filter((b) => b.outcome !== "dropped").sort((a, b) => a.t - b.t)[0];
if (first) {
  await page.$eval(".break-list button", (el) => el.click());
  await page.waitForFunction((t) => document.querySelector(".trace-time")?.textContent === t, {}, clock(first.t));
  check(true, "the Ad breaks list opens the matching trace");
}

// The URL follows the selection, and a shared link opens the same candidate.
const target = report.candidates[report.candidates.length - 1];
await (await page.$$(".tl-mark"))[report.candidates.length - 1].evaluate((el) => el.click());
await page.waitForFunction((t) => document.querySelector(".trace-time")?.textContent === t, {}, clock(target.t));
const hash = await page.evaluate(() => location.hash);
check(hash === `#/watch/${name}?t=${target.t}`, "the URL reflects the selected candidate", `(${hash})`);
await page.goto(`${BASE}/${hash}`, { waitUntil: "networkidle2" });
await page.reload({ waitUntil: "networkidle2" });
await page.waitForSelector(".trace-time");
check((await page.$eval(".trace-time", (e) => e.textContent)) === clock(target.t), "a shared link opens that candidate");

await browser.close();
console.log(failures.length ? `\nFAILED: ${failures.length} check(s)` : "\nALL CHECKS PASSED");
process.exit(failures.length ? 1 : 0);
