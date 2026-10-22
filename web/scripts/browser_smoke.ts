// Headless browser check of the page: load time, queries, console errors. Needs the dev server on :5173.
import { chromium } from "playwright";

const QUERIES = ["districts near the sea in Gujarat", "hospitals within 2 km of coastal districts of Odisha",
  "2 km around MG Road Bangalore", "Kerala except Palakkad", "what is the weather in Pune"];
const browser = await chromium.launch();
const page = await browser.newPage();
const errors: string[] = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 300)); });
page.on("pageerror", (e) => errors.push(String(e).slice(0, 300)));
let bytes = 0;
const byFile: Record<string, number> = {};
page.on("requestfinished", async (req) => {
  const s = await req.sizes().catch(() => null);
  if (!s) return;
  bytes += s.responseBodySize;
  const f = req.url().split("?")[0].split("/").slice(-1)[0];
  byFile[f] = (byFile[f] ?? 0) + s.responseBodySize;
});
const t0 = Date.now();
await page.goto("http://localhost:5173/");
await page.waitForFunction(() => document.getElementById("status")!.textContent!.startsWith("Ready") ||
  document.getElementById("status")!.textContent!.includes("failed"), null, { timeout: 600000 });
console.log("load:", await page.textContent("#status"), `(${((Date.now() - t0) / 1000).toFixed(1)} s wall, ${(bytes / 1e6).toFixed(0)} MB transferred)`);
console.log("largest:", Object.entries(byFile).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([f, b]) => `${f} ${(b / 1e6).toFixed(1)} MB`).join(", "));
const atLoad = bytes;
for (const q of QUERIES) {
  await page.fill("#q", q);
  const t = Date.now();
  await page.click("#go");
  await page.waitForFunction(() => !(document.getElementById("go") as HTMLButtonElement).disabled, null, { timeout: 300000 });
  const head = (await page.textContent("#side h3"))?.trim();
  const p = (await page.$$eval("#side > p", (els) => els.map((e) => e.textContent))).join(" | ");
  console.log(`${((Date.now() - t) / 1000).toFixed(1)}s`, JSON.stringify(q), "->", head, "|", p.slice(0, 160), "|", await page.textContent("#status"));
}
console.log(`transferred during queries: ${((bytes - atLoad) / 1e6).toFixed(1)} MB`);
await page.screenshot({ path: "test/browser.png" });
console.log("console errors:", errors.length, errors.slice(0, 5));
await browser.close();
