import maplibregl from "maplibre-gl";
import { onDownload, type Download } from "../core/progress.ts";
import { load, type Geoparse } from "../geoparse.ts";
import type { Result } from "../execute/executor.ts";
import type { ParseResult } from "../parse/pipeline.ts";
import { decisions, esc, headline, HOW_IT_WORKS, reading } from "./explain.ts";

const $ = (id: string) => document.getElementById(id)!;
const status = $("status"), side = $("side"), q = $("q") as HTMLInputElement, go = $("go") as HTMLButtonElement;
// Examples: tasks of geo analysis in many countries (plan-028; checked with SET=examples of scripts/world_smoke.ts).
const EXAMPLES: [string, string[]][] = [
  ["Places", ["Boudh", "the British Isles", "Porto", "Washington DC"]],
  ["Buildings and streets", ["5 km buffer around the Taj Mahal", "2 km around the Eiffel Tower", "500 m around Shibuya Crossing",
    "MG Road, Bangalore"]],
  ["Study areas", ["counties of Kenya", "districts of Bavaria", "northern Italy", "Bavaria except Munich"]],
  ["Around a place", ["20 km around Nairobi", "10 km around Manchester", "schools in Pune", "cities in California with population over 1 million"]],
  ["Borders", ["states that border Texas", "provinces of South Africa that border Mozambique",
    "10 km zone along the border of India and Pakistan", "border between the United States and Mexico"]],
  ["Natural features", ["Sahara desert", "counties along the Mississippi", "districts along the Ganga", "countries near the Himalayas"]],
  ["Regions", ["Pacific Northwest", "the Middle East", "countries of the Balkans", "Southeast Asia"]],
  ["Filters and ranks", ["coastal states of Mexico", "coastal provinces of Vietnam", "the 5 largest states of Brazil"]],
  ["Same name, other place", ["Paris, Texas"]],
];

// Basemap: VersaTiles (free, no API key; data © OpenStreetMap contributors). EasyPrivacy blocks the OpenFreeMap tiles
// (easylist/easylist#26522).
// Without WebGL there is no map; the queries and the result list still work.
const STYLE = "https://tiles.versatiles.org/assets/styles/gray/style.json";
let map: maplibregl.Map | null = null;
try {
  // Arabic and Hebrew labels: the plugin loads only when a tile has right-to-left text.
  maplibregl.setRTLTextPlugin("https://unpkg.com/@mapbox/mapbox-gl-rtl-text@0.4.0/dist/mapbox-gl-rtl-text.js", true).catch(console.error);
  map = new maplibregl.Map({ container: "map", style: STYLE, center: [78.9, 22.5], zoom: 4 });
} catch (e) {
  $("map").innerHTML = `<p class="err" style="padding:16px">The map cannot show in this browser (WebGL is not available).
    The results show in the list.</p>`;
  console.error(e);
}
// MapLibre does not try again when the style or a TileJSON fails to load (a short network error), and the basemap stays empty.
const retries = new Map<string, number>();
map?.on("error", (e: any) => {
  const url: string | undefined = e.error?.url;
  if (!map || !url || e.tile) return;
  const n = retries.get(url) ?? 0;
  if (n >= 6) return;
  retries.set(url, n + 1);
  setTimeout(() => {
    if (url === STYLE) return map!.setStyle(STYLE);
    const sources = map!.getStyle()?.sources ?? {};
    for (const [id, s] of Object.entries(sources))
      if ((s as any).url === url) (map!.getSource(id) as maplibregl.VectorTileSource).setUrl(url);
  }, 1000 * 2 ** n);
});
const mapReady = new Promise<void>((res) => (!map || map.loaded() ? res() : map.once("load", () => res())));
// For scripts/world_smoke.ts: set the map view before a query.
(window as any).geoparseMap = map;

let gp: Geoparse;

const ACCENT = "#D04200";

async function show(fc: any) {
  await mapReady;
  if (!map) return;
  const src = map.getSource("result") as maplibregl.GeoJSONSource | undefined;
  if (src) src.setData(fc);
  else {
    map.addSource("result", { type: "geojson", data: fc });
    map.addLayer({ id: "fill", type: "fill", source: "result", filter: ["==", ["geometry-type"], "Polygon"], paint: { "fill-color": ACCENT, "fill-opacity": 0.16 } });
    map.addLayer({ id: "line", type: "line", source: "result", paint: { "line-color": ACCENT, "line-width": 2 } });
    map.addLayer({ id: "pts", type: "circle", source: "result", filter: ["==", ["geometry-type"], "Point"], paint: { "circle-radius": 4.5, "circle-color": ACCENT, "circle-stroke-color": "#FFFFFF", "circle-stroke-width": 1.5 } });
  }
  const b = new maplibregl.LngLatBounds();
  const walk = (c: any) => (!c?.length ? undefined : typeof c[0] === "number" ? b.extend(c as [number, number]) : c.forEach(walk));
  // A geometry collection (some merged rivers) has its parts in `geometries`, not coordinates.
  const geom = (g: any) => (g?.type === "GeometryCollection" ? g.geometries.forEach(geom) : walk(g?.coordinates));
  fc.features.forEach((f: any) => geom(f.geometry));
  if (!b.isEmpty()) map.fitBounds(b, { padding: 40, maxZoom: 14, duration: 500 });
}

// Before the first query the page is a landing page; after it, a compact header over the map and the results.
function setLanding(on: boolean) {
  document.body.classList.toggle("landing", on);
  document.body.classList.remove("show-examples");
  $("more").textContent = "Show examples";
  // The map container changes size with the layout.
  map?.resize();
  if (map) for (const ms of [400, 800]) setTimeout(() => map!.resize(), ms);
}

// Number of the current query: a query that took too long does not show its result when it ends later.
let current = 0;
let lastProgress = 0;

async function runQuery(text: string) {
  if (document.body.classList.contains("landing")) setLanding(false);
  else { document.body.classList.remove("show-examples"); $("more").textContent = "Show examples"; }
  go.disabled = true;
  const id = ++current;
  const limit = Number(gp.bundle.config.web?.query_timeout_s ?? 90);
  // The limit is for time without progress: a download that is still arriving (a slow network) restarts the clock.
  lastProgress = performance.now();
  let timer = 0;
  const timeout = new Promise<"timeout">((res) => {
    timer = window.setInterval(() => { if (performance.now() - lastProgress > limit * 1000) res("timeout"); }, 1000);
  });
  try {
    if ((await Promise.race([runQuery_(text, id), timeout])) === "timeout") {
      current++;
      queryStatus = "";
      $("busy").hidden = true;
      status.innerHTML = `<span class="err">The query took too long (no progress for ${limit} s).</span>`;
      side.innerHTML = `<h3><span class="err">The query took too long</span></h3><p>The app stopped waiting after ${limit} s
        without progress. Try a smaller area or a more exact query. The next query can be slow while the browser finishes this one.</p>`;
    }
  } catch (e) {
    if (id !== current) return;
    queryStatus = "";
    $("busy").hidden = true;
    status.innerHTML = `<span class="err">Error: ${esc((e as Error).message)}</span>`;
    side.innerHTML = `<h3><span class="err">Something went wrong</span></h3><p>${esc((e as Error).message)}</p>`;
    console.error(e);
  } finally {
    clearInterval(timer);
    go.disabled = false;
  }
}

// Progress of a query: the status line, a pill over the map, and a card in the result panel.
function showProgress(msg: string) {
  status.textContent = msg;
  $("busy-text").textContent = msg;
  const card = document.getElementById("working-text");
  if (card) card.textContent = msg;
}

function setStep(step: string, id: number) {
  if (id !== current) return;
  queryStatus = step;
  showProgress(step);
}

async function runQuery_(text: string, id: number) {
  files.clear();
  $("busy").hidden = false;
  // The result of the last query goes away, so that the map does not show it as the answer to this one.
  (map?.getSource("result") as maplibregl.GeoJSONSource | undefined)?.setData({ type: "FeatureCollection", features: [] });
  side.innerHTML = `<div class="working"><span class="spin" aria-hidden="true"></span><span id="working-text"></span></div>`;
  setStep("Reading your query…", id);
  const t0 = performance.now();
  // The map view biases the ranking of places with the same name.
  const b = map?.getBounds();
  const view = b ? [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()] : null;
  let p: ParseResult, r: Result | null = null;
  try {
    p = await gp.parse(text, view);
    if (p.ok) {
      setStep("Finding the places…", id);
      r = await gp.execute(p.dag, view);
    }
  } finally {
    if (id === current) $("busy").hidden = true;
  }
  // A query that took too long: the page shows the time-out message, not this result.
  if (id !== current) return;
  const total = (performance.now() - t0) / 1000;
  queryStatus = "";
  status.textContent = `${p.ok ? "" : "Not understood · "}parse ${p.timings.parse_s.toFixed(2)} s · total ${total.toFixed(2)} s`;
  const fc = { type: "FeatureCollection", features: (r?.features ?? []).filter((f) => f.geometry).map((f) => ({ type: "Feature", geometry: f.geometry, properties: { name: f.name, id: f.id } })) };
  await show(fc);
  const feats = r?.features ?? [];
  side.innerHTML = `
    <h3>${headline(p, r)}</h3>
    ${r ? `<p>${r.ok ? `${feats.length} result${feats.length === 1 ? "" : "s"} in ${(r.timings.total_s ?? 0).toFixed(2)} s` : `<span class="err">${esc(r.error)}</span>`}</p>` : ""}
    ${[...(p.notes ?? []), ...(r?.notes ?? [])].map((n) => `<p>⚠ ${esc(n)}</p>`).join("")}
    ${HOW_IT_WORKS}
    <h4>How the app read the query</h4>${reading(p, gp.bundle)}
    ${feats.length ? `<h4>Results</h4><table id="features"><tr><th>Name</th><th>Type</th><th>Source</th></tr>${feats.slice(0, 200).map((f) =>
      `<tr><td>${esc(f.name)}</td><td>${esc(f.subtype)}</td><td>${esc(f.source)}</td></tr>`).join("")}</table>
      ${feats.length > 200 ? `<p class="muted">The first 200 of ${feats.length}.</p>` : ""}` : ""}
    <h4>Decisions</h4>
    <p class="muted">The questions that the models and the rules answered to read the query, in order. Indented questions are about a part of the query.</p>
    ${decisions(p.trace, gp.bundle)}
    ${p.dag ? `<h4>Plan</h4><p class="muted">The steps that make the answer. Each <code>op</code> is one step. Its <code>args</code> are its inputs; an input can be another step.</p>
      <pre>${esc(JSON.stringify(p.dag, null, 1))}</pre>` : ""}
    <details><summary>Technical details</summary>
      <h4>Slots</h4><pre>${esc(JSON.stringify(p.slots, null, 1))}</pre>
      <table><tr><th>depth</th><th>decision</th><th>value</th><th>conf</th><th>impl</th><th>ms</th></tr>
      ${p.trace.map((t) => `<tr><td>${t.depth}</td><td>${esc(t.decision)}</td><td>${esc(typeof t.value === "string" ? t.value : JSON.stringify(t.value)).slice(0, 140)}</td>
        <td class="${t.confidence < t.threshold ? "err" : ""}">${t.confidence.toFixed(2)}</td><td>${esc(t.impl)}</td><td>${(t.latency_s * 1000).toFixed(0)}</td></tr>`).join("")}
      </table><p>Template ${esc(p.template)} (${esc(p.path)}), parse ${p.timings.parse_s.toFixed(2)} s.</p></details>`;
}

$("examples").innerHTML = EXAMPLES.map(([g, qs]) => `<div class="group"><div class="label">${esc(g)}</div><div class="items">${qs.map((e) =>
  `<button type="button" data-q="${esc(e)}">${esc(e)}</button>`).join("")}</div></div>`).join("");
$("examples").addEventListener("click", (ev) => {
  const b = (ev.target as HTMLElement).closest("button");
  if (b && !go.disabled) { q.value = b.dataset.q!; runQuery(q.value); }
});
$("form").addEventListener("submit", (e) => {
  e.preventDefault();
  if (!go.disabled && q.value) runQuery(q.value);
});
$("more").onclick = () => $("more").textContent = document.body.classList.toggle("show-examples") ? "Hide examples" : "Show examples";
$("home").onclick = () => setLanding(true);

// Loading screen: one row for each part, with the downloaded and the expected megabytes.
const STEPS: [string, string][] = [["settings", "Settings and the database engine"], ["data", "Place data (names and borders)"],
  ["t5", "Language model (reads your query)"], ["xenc", "Decision model (chooses between options)"]];
const partOf = (file: string) => (file.startsWith("t5/") ? "t5" : file.startsWith("xenc/") ? "xenc" : "data");
const files = new Map<string, Download>();
const done = new Set<string>();
const mb = (n: number) => (n / 1e6).toFixed(1);
const CHECK = `<svg role="img" aria-label="Done" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="3.5"
  stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"></path></svg>`;
$("steps").innerHTML = STEPS.map(([k, label]) => `<div class="step" id="step-${k}"><span class="mark"></span>
  <div class="line"><span class="label">${label}</span><span class="size"></span></div><div class="bar"><i></i></div></div>`).join("");
let frame = 0;
function drawSteps() {
  frame = 0;
  const all = [...files.values()];
  const got = all.reduce((a, d) => a + d.loaded, 0), of = all.reduce((a, d) => a + d.total, 0);
  $("total").textContent = of ? `${mb(got)} / ${mb(of)} MB` : "";
  $("total-bar").style.width = of ? `${(100 * got) / of}%` : "0";
  for (const [k] of STEPS) {
    const fs = [...files.values()].filter((d) => partOf(d.file) === k);
    const loaded = fs.reduce((a, d) => a + d.loaded, 0), total = fs.reduce((a, d) => a + d.total, 0);
    const el = $(`step-${k}`);
    el.classList.toggle("done", done.has(k));
    el.querySelector(".mark")!.innerHTML = done.has(k) ? CHECK : "";
    el.querySelector(".size")!.textContent = total ? `${mb(loaded)} / ${mb(total)} MB` : "";
    (el.querySelector(".bar i") as HTMLElement).style.width = done.has(k) ? "100%" : total ? `${(100 * loaded) / total}%` : "0";
  }
}
const redraw = () => { frame ||= requestAnimationFrame(drawSteps); };

// After the start: the files that a query loads (for example the countries of the places in the query).
const countryName = (() => {
  try { const d = new Intl.DisplayNames(["en"], { type: "region" }); return (c: string) => d.of(c) ?? c; } catch { return (c: string) => c; }
})();
function fileLabel(file: string): string {
  const cc = /^country=(\w+)\//.exec(file)?.[1];
  if (cc === "QN") return "natural features";
  if (cc) return countryName(cc);
  if (file.startsWith("names/")) return "place names";
  if (file.includes("layers")) return "coastlines and borders";
  if (file.includes("admin_areas")) return "country and state outlines";
  if (file.includes("country_shapes")) return "country shapes";
  return file;
}
let queryStatus = "";
function drawQueryLoads() {
  frame = 0;
  if (!queryStatus) return;
  // All files of this query in the sum, so that the total does not go down when a file is done.
  const all = [...files.values()], active = all.filter((d) => !d.done);
  if (!active.length) { showProgress(queryStatus); return; }
  const loaded = all.reduce((a, d) => a + d.loaded, 0), total = all.reduce((a, d) => a + d.total, 0);
  const names = [...new Set(active.map((d) => fileLabel(d.file)))].join(", ");
  showProgress(`${queryStatus} Loading data for ${names} (${mb(loaded)}${total ? ` / ${mb(total)}` : ""} MB)…`);
}
let ready = false;
onDownload((d) => {
  files.set(d.file, d);
  lastProgress = performance.now();
  if (ready) frame ||= requestAnimationFrame(drawQueryLoads);
  else {
    // "Loading": the page cannot see if a file comes from the network or from the browser cache.
    if (!d.done) $("now").innerHTML = `<span>Loading <code>${esc(d.file)}</code></span>`;
    redraw();
  }
});

function progress(m: string) {
  status.textContent = `Loading ${m}…`;
  if (m === "data, models") done.add("settings");
  if (m === "T5 model loaded") done.add("t5");
  if (m === "decision model loaded") done.add("xenc");
  if (m.startsWith("data: country")) done.add("data");
  redraw();
}

const t0 = performance.now();
// ?data=<url>: other data files, for example the country layout (public/countries/<release>).
// A deployed build gets the data and model URLs from the deploy script (VITE_DATA_URL, VITE_MODEL_URL, VITE_DATA_VERSION).
const env = import.meta.env;
const param = new URLSearchParams(location.search).get("data");
const data = param ?? (env.VITE_DATA_URL || undefined);
load("", progress, data,
  { models: env.VITE_MODEL_URL || undefined, dataVersion: param ? "" : env.VITE_DATA_VERSION || "", preload: false }).then((g) => {
  gp = g;
  go.disabled = false;
  const total = [...files.values()].reduce((a, d) => a + d.loaded, 0);
  status.textContent = `Ready in ${((performance.now() - t0) / 1000).toFixed(1)} s (${mb(total)} MB). Everything runs in this browser tab.`;
  ready = true;
  files.clear();
  $("loading").hidden = true;
  (window as any).geoparse = g;
}).catch((e) => {
  status.innerHTML = `<span class="err">Load failed: ${esc(e.message)}</span>`;
  $("now").innerHTML = `<span class="err">Loading failed: ${esc(e.message)}</span><button type="button" onclick="location.reload()">Try again</button>`;
  console.error(e);
});
