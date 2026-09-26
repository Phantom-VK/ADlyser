// Screenshot pages for a visual check: [HEIGHT=900] [FULL=0] node scripts/shots.mjs <outdir> <width> <hash>...   (dev servers must be running)
import { mkdirSync } from "node:fs";
import puppeteer from "puppeteer-core";

const [out, width, ...hashes] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const browser = await puppeteer.launch({
  executablePath: process.env.CHROME ?? "/usr/bin/google-chrome",
  headless: true,
  args: ["--autoplay-policy=no-user-gesture-required", "--no-sandbox"],
});
const page = await browser.newPage();
await page.setViewport({ width: Number(width), height: Number(process.env.HEIGHT ?? 900) });
const problems = [];
page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
page.on("console", (m) => ["error", "warning"].includes(m.type()) && problems.push(`${m.type()}: ${m.text()}`));
page.on("requestfailed", (r) => problems.push(`requestfailed: ${r.url()}`));
for (const [i, hash] of hashes.entries()) {
  await page.goto(`${process.env.BASE ?? "http://127.0.0.1:5173"}/${hash}`, { waitUntil: "networkidle2" });
  await new Promise((r) => setTimeout(r, 1500));
  await page.screenshot({ path: `${out}/${i}.png`, fullPage: process.env.FULL !== "0" });
}
console.log(problems.length ? problems.join("\n") : "no console problems");
await browser.close();
