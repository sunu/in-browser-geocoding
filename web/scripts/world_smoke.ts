// World data in the page (plan-008 phase 4): start-up bytes, then queries in several countries with the map view
// on each country. Bytes and time for each query. Needs the dev server.
// Usage: [SET=poi] PAGE="http://localhost:5180/?data=https://files.geoparse.labs.sunu.in/2026-10-21.0" npx tsx scripts/world_smoke.ts [chromium|firefox|webkit]
import { chromium, firefox, webkit } from "playwright";

const VIEWS: Record<string, number[]> = {
  IN: [68, 6.5, 97.5, 37.2], US: [-125, 24, -66, 50], FR: [-5, 41, 10, 51.5], BR: [-74, -34, -34, 5.5], JP: [129, 30, 146, 46],
};
const BASE: [string, string][] = [
  ["IN", "Kerala except Palakkad"], ["IN", "districts near the sea in Gujarat"],
  ["US", "counties of Nevada"], ["US", "states that border Nevada"], ["US", "Springfield"],
  ["FR", "Lyon"], ["FR", "districts of Bretagne"],
  ["BR", "cities in Minas Gerais with population over 1 million"], ["BR", "Recife"],
  ["JP", "Osaka"], ["JP", "Hokkaido"],
  ["US", "San Jose"], ["IN", "San Jose"],
];
// Hospitals and schools from the world point datasets (plan-008 phase 5). Pharmacies have no local data (Photon).
const POI: [string, string][] = [
  ["IN", "hospitals in Ernakulam"], ["IN", "schools in Pune"], ["US", "hospitals in San Francisco"], ["US", "schools in Reno"],
  ["FR", "hospitals in Lyon"], ["BR", "schools in Recife"], ["JP", "hospitals in Sapporo"], ["FR", "pharmacies in Lyon"],
];
// Natural features, qualified names and the reviewed templates (plan-025, phases 10 to 13).
const NEW: [string, string][] = [
  ["IN", "Ganga river"], ["IN", "districts along the Yamuna"], ["IN", "5 largest districts of Karnataka"],
  ["FR", "border between Spain and Portugal"], ["US", "Paris, Texas"], ["FR", "districts in northern France"],
  ["IN", "states that border both Karnataka and Kerala"], ["IN", "riverside districts of Bihar"],
];
const QUERIES = process.env.SET === "poi" ? POI : process.env.SET === "new" ? NEW : BASE;
const name = process.argv[2] ?? "chromium";
// Headless Firefox on Linux without a GPU driver has no WebGL (the map needs it): use the software renderer.
const browser = await ({ chromium, firefox, webkit } as any)[name].launch(
  name === "firefox" ? { firefoxUserPrefs: { "webgl.force-enabled": true, "webgl.disabled": false } } : {});
const page = await browser.newPage();
const errors: string[] = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 300)); });
page.on("pageerror", (e) => errors.push(String(e).slice(0, 300)));
let bytes = 0, requests = 0, poiBytes = 0, poiReq = 0;
const files: Record<string, number> = {};
page.on("requestfinished", async (req) => {
  const s = await req.sizes().catch(() => null);
  if (!s) return;
  bytes += s.responseBodySize;
  requests++;
  const u = req.url().split("?")[0];
  if (u.includes("/poi/")) { poiBytes += s.responseBodySize; poiReq++; }
  if (u.includes("files.geoparse")) files[u.split("2026-10-21.0/")[1] ?? u] = s.responseBodySize;
});
const t0 = Date.now();
await page.goto(process.env.PAGE ?? "http://localhost:5180/");
await page.waitForFunction(() => document.getElementById("status")!.textContent!.startsWith("Ready") ||
  document.getElementById("status")!.textContent!.includes("failed"), null, { timeout: 600000 });
const dataAtLoad = Object.values(files).reduce((a, b) => a + b, 0);
console.log("load:", await page.textContent("#status"), `(${((Date.now() - t0) / 1000).toFixed(1)} s wall, ${(bytes / 1e6).toFixed(0)} MB, data ${(dataAtLoad / 1e6).toFixed(1)} MB)`);
console.log("data files at load:", Object.entries(files).map(([f, b]) => `${f} ${(b / 1e6).toFixed(2)}`).join(", "));
for (const [cc, q] of QUERIES) {
  await page.evaluate((v) => (window as any).geoparseMap.fitBounds([[v[0], v[1]], [v[2], v[3]]], { animate: false }), VIEWS[cc]);
  const b0 = bytes, r0 = requests, pb0 = poiBytes, pr0 = poiReq, f0 = new Set(Object.keys(files));
  await page.fill("#q", q);
  const t = Date.now();
  await page.click("#go");
  await page.waitForFunction(() => !(document.getElementById("go") as HTMLButtonElement).disabled, null, { timeout: 300000 });
  const head = (await page.textContent("#side h3"))?.trim();
  const p = (await page.$$eval("#side > p", (els) => els.map((e) => e.textContent))).join(" | ");
  const newFiles = Object.keys(files).filter((f) => !f0.has(f));
  const countries = [...new Set(newFiles.map((f) => f.match(/country=(\w+)/)?.[1]).filter(Boolean))];
  console.log(`[${cc}] ${((Date.now() - t) / 1000).toFixed(1)}s ${((bytes - b0) / 1e6).toFixed(1)} MB ${requests - r0} req`,
    JSON.stringify(q), "->", head, "|", p.slice(0, 140), "| loaded:", countries.join(" "), newFiles.filter((f) => f.startsWith("names/")).length, "shards",
    poiReq > pr0 ? `| poi ${poiReq - pr0} req ${((poiBytes - pb0) / 1e6).toFixed(2)} MB` : "");
}
console.log("console errors:", errors.length, errors.slice(0, 5));
await browser.close();
