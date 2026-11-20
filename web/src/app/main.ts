import maplibregl from "maplibre-gl";
import { onDownload, type Download } from "../core/progress.ts";
import { load, type Geoparse } from "../geoparse.ts";
import { decisions, esc, headline, HOW_IT_WORKS, reading } from "./explain.ts";

const $ = (id: string) => document.getElementById(id)!;
const status = $("status"), side = $("side"), q = $("q") as HTMLInputElement, go = $("go") as HTMLButtonElement;
// Examples: tasks of geo analysis in many countries (plan-028; checked with SET=examples of scripts/world_smoke.ts).
const EXAMPLES: [string, string[]][] = [
  ["Places", ["Boudh", "the British Isles", "Porto", "Washington DC"]],
  ["Study areas", ["counties of Kenya", "districts of Bavaria", "northern Italy", "Bavaria except Munich"]],
  ["Around a place", ["20 km around Nairobi", "10 km around Manchester", "schools in Pune", "cities in California with population over 1 million"]],
  ["Borders", ["states that border Texas", "provinces of South Africa that border Mozambique",
    "10 km zone along the border of India and Pakistan", "border between the United States and Mexico"]],
  ["Natural features", ["Sahara desert", "counties along the Mississippi", "districts along the Ganga"]],
  ["Filters and ranks", ["coastal states of Mexico", "coastal provinces of Vietnam", "the 5 largest states of Brazil"]],
  ["Same name, other place", ["Paris, Texas"]],
];

// Basemap: OpenFreeMap (free, no API key; data © OpenStreetMap contributors).
// Without WebGL there is no map; the queries and the result list still work.
let map: maplibregl.Map | null = null;
try {
  map = new maplibregl.Map({
    container: "map", style: "https://tiles.openfreemap.org/styles/positron", center: [78.9, 22.5], zoom: 4,
  });
} catch (e) {
  $("map").innerHTML = `<p class="err" style="padding:16px">The map cannot show in this browser (WebGL is not available).
    The results show in the list.</p>`;
  console.error(e);
}
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
  const walk = (c: any) => (typeof c[0] === "number" ? b.extend(c as [number, number]) : c.forEach(walk));
  fc.features.forEach((f: any) => f.geometry && walk(f.geometry.coordinates));
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

async function runQuery(text: string) {
  if (document.body.classList.contains("landing")) setLanding(false);
  else { document.body.classList.remove("show-examples"); $("more").textContent = "Show examples"; }
  go.disabled = true;
  try { await runQuery_(text); } catch (e) {
    queryStatus = "";
    status.innerHTML = `<span class="err">Error: ${esc((e as Error).message)}</span>`;
    console.error(e);
  } finally { go.disabled = false; }
}

async function runQuery_(text: string) {
  files.clear();
  queryStatus = "Working…";
  status.textContent = queryStatus;
  const t0 = performance.now();
  // The map view biases the ranking of places with the same name.
  const b = map?.getBounds();
  const { parse: p, result: r } = await gp.run(text, b ? [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()] : null);
  const total = (performance.now() - t0) / 1000;
  queryStatus = "";
  status.textContent = `${p.ok ? "" : "Not understood · "}parse ${p.timings.parse_s.toFixed(2)} s · total ${total.toFixed(2)} s`;
  const fc = { type: "FeatureCollection", features: (r?.features ?? []).filter((f) => f.geometry).map((f) => ({ type: "Feature", geometry: f.geometry, properties: { name: f.name, id: f.id } })) };
  await show(fc);
  const feats = r?.features ?? [];
  side.innerHTML = `
    <h3>${headline(p, r)}</h3>
    ${r ? `<p>${r.ok ? `${feats.length} result${feats.length === 1 ? "" : "s"} in ${(r.timings.total_s ?? 0).toFixed(2)} s` : `<span class="err">${esc(r.error)}</span>`}</p>` : ""}
    ${(r?.notes ?? []).map((n) => `<p>⚠ ${esc(n)}</p>`).join("")}
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
  if (file.includes("country_shapes")) return "country shapes";
  return file;
}
let queryStatus = "";
function drawQueryLoads() {
  frame = 0;
  if (!queryStatus) return;
  // All files of this query in the sum, so that the total does not go down when a file is done.
  const all = [...files.values()], active = all.filter((d) => !d.done);
  if (!active.length) { status.textContent = queryStatus; return; }
  const loaded = all.reduce((a, d) => a + d.loaded, 0), total = all.reduce((a, d) => a + d.total, 0);
  const names = [...new Set(active.map((d) => fileLabel(d.file)))].join(", ");
  status.textContent = `${queryStatus} Loading data for ${names} (${mb(loaded)}${total ? ` / ${mb(total)}` : ""} MB)…`;
}
let ready = false;
onDownload((d) => {
  files.set(d.file, d);
  if (ready) frame ||= requestAnimationFrame(drawQueryLoads);
  else {
    if (!d.done) $("now").innerHTML = `<span>Downloading <code>${esc(d.file)}</code></span>`;
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
  { models: env.VITE_MODEL_URL || undefined, dataVersion: param ? "" : env.VITE_DATA_VERSION || "" }).then((g) => {
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
