import maplibregl from "maplibre-gl";
import { load, type Geoparse } from "../geoparse.ts";

const $ = (id: string) => document.getElementById(id)!;
const status = $("status"), side = $("side"), q = $("q") as HTMLInputElement, go = $("go") as HTMLButtonElement;
const EXAMPLES = ["districts near the sea in Gujarat", "hospitals within 2 km of coastal districts of Odisha", "2 km around MG Road Bangalore",
  "Kerala except Palakkad", "states that border Karnataka", "cities in Maharashtra with population over 1 million", "northern Karnataka"];

// Basemap: OpenFreeMap (free, no API key; data © OpenStreetMap contributors).
const map = new maplibregl.Map({
  container: "map", style: "https://tiles.openfreemap.org/styles/positron", center: [78.9, 22.5], zoom: 4,
});
const mapReady = new Promise<void>((res) => (map.loaded() ? res() : map.once("load", () => res())));

let gp: Geoparse;
const esc = (s: any) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));

async function show(fc: any) {
  await mapReady;
  const src = map.getSource("result") as maplibregl.GeoJSONSource | undefined;
  if (src) src.setData(fc);
  else {
    map.addSource("result", { type: "geojson", data: fc });
    map.addLayer({ id: "fill", type: "fill", source: "result", filter: ["==", ["geometry-type"], "Polygon"], paint: { "fill-color": "#2563eb", "fill-opacity": 0.25 } });
    map.addLayer({ id: "line", type: "line", source: "result", paint: { "line-color": "#1e40af", "line-width": 1.2 } });
    map.addLayer({ id: "pts", type: "circle", source: "result", filter: ["==", ["geometry-type"], "Point"], paint: { "circle-radius": 4, "circle-color": "#dc2626" } });
  }
  const b = new maplibregl.LngLatBounds();
  const walk = (c: any) => (typeof c[0] === "number" ? b.extend(c as [number, number]) : c.forEach(walk));
  fc.features.forEach((f: any) => f.geometry && walk(f.geometry.coordinates));
  if (!b.isEmpty()) map.fitBounds(b, { padding: 40, maxZoom: 14, duration: 500 });
}

async function runQuery(text: string) {
  go.disabled = true;
  status.textContent = "Parsing…";
  const t0 = performance.now();
  const { parse: p, result: r } = await gp.run(text);
  const total = (performance.now() - t0) / 1000;
  status.textContent = `${p.ok ? "OK" : "Unsupported"} · parse ${p.timings.parse_s.toFixed(2)} s · total ${total.toFixed(2)} s`;
  const fc = { type: "FeatureCollection", features: (r?.features ?? []).filter((f) => f.geometry).map((f) => ({ type: "Feature", geometry: f.geometry, properties: { name: f.name, id: f.id } })) };
  await show(fc);
  side.innerHTML = `
    <h3>${p.ok ? `<span class="ok">${esc(p.template)}</span> (${esc(p.path)})` : `<span class="err">Unsupported</span>: ${esc(p.unsupported?.reason)}`}</h3>
    ${r ? `<p>${r.ok ? `${r.features.length} feature(s), ${r.kind}, execute ${(r.timings.total_s ?? 0).toFixed(2)} s` : `<span class="err">${esc(r.error)}</span>`}</p>` : ""}
    ${(r?.notes ?? []).map((n) => `<p>⚠ ${esc(n)}</p>`).join("")}
    <h4>Slots</h4><pre>${esc(JSON.stringify(p.slots, null, 1))}</pre>
    <h4>Decisions</h4>
    <table><tr><th>depth</th><th>decision</th><th>value</th><th>conf</th><th>impl</th><th>ms</th></tr>
    ${p.trace.map((t) => `<tr><td>${t.depth}</td><td>${esc(t.decision)}</td><td>${esc(typeof t.value === "string" ? t.value : JSON.stringify(t.value)).slice(0, 140)}</td>
      <td class="${t.confidence < t.threshold ? "err" : ""}">${t.confidence.toFixed(2)}</td><td>${esc(t.impl)}</td><td>${(t.latency_s * 1000).toFixed(0)}</td></tr>`).join("")}
    </table>
    ${p.dag ? `<h4>DAG</h4><pre>${esc(JSON.stringify(p.dag, null, 1))}</pre>` : ""}
    ${r?.features?.length ? `<h4>Features</h4><table>${r.features.slice(0, 200).map((f) => `<tr><td>${esc(f.name)}</td><td>${esc(f.subtype)}</td><td>${esc(f.source)}</td></tr>`).join("")}</table>` : ""}`;
  go.disabled = false;
}

$("examples").innerHTML = EXAMPLES.map((e) => `<button data-q="${esc(e)}">${esc(e)}</button>`).join("");
$("examples").addEventListener("click", (ev) => {
  const b = (ev.target as HTMLElement).closest("button");
  if (b && !go.disabled) { q.value = b.dataset.q!; runQuery(q.value); }
});
go.onclick = () => q.value && runQuery(q.value);
q.onkeydown = (e) => { if (e.key === "Enter" && !go.disabled && q.value) runQuery(q.value); };

const t0 = performance.now();
// ?data=<url>: other data files, for example the country layout (public/countries/<release>).
const data = new URLSearchParams(location.search).get("data") ?? undefined;
load("", (m) => (status.textContent = `Loading ${m}…`), data).then((g) => {
  gp = g;
  go.disabled = false;
  status.textContent = `Ready in ${((performance.now() - t0) / 1000).toFixed(1)} s. Everything runs in this browser tab.`;
  (window as any).geoparse = g;
}).catch((e) => { status.innerHTML = `<span class="err">Load failed: ${esc(e.message)}</span>`; console.error(e); });
