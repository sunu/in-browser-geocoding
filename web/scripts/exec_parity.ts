// Executor parity: execute the gold DAGs in JS and compare the result IDs with gold expected_ids.
// Run: [DATA=public/countries/<release>] [SETS=gold,heldout] npx tsx scripts/exec_parity.ts
import fs from "node:fs";
import { loadBundle } from "../src/core/bundle.ts";
import { openDb } from "../src/execute/db.ts";
import { Executor } from "../src/execute/executor.ts";
import { Photon } from "../src/execute/photon.ts";

const pub = new URL("../public", import.meta.url).pathname;
const bundle = await loadBundle(pub + "/bundle.json");
const db = await openDb(process.env.DATA ?? pub + "/data", undefined, bundle.config.data.country);
const ex = new Executor(db, bundle, new Photon());
// SETS: gold files (default gold,heldout; "ops": the operator tests of gold/build_ops.py, with the world data).
const rows = (process.env.SETS ?? "gold,heldout").split(",").flatMap((n) => fs.readFileSync(new URL(`../../gold/${n}.jsonl`, import.meta.url), "utf8").trim().split("\n").map((l) => JSON.parse(l)));
let same = 0, n = 0, geomOk = 0, nGeom = 0;
const lat: number[] = [];
for (const r of rows) {
  if (r.expected_ids === null) continue;
  const res = await ex.execute(r.dag, !!r.expected_geometry);
  lat.push(res.timings.total_s ?? 0);
  if ((res.timings.total_s ?? 0) > 10) console.log("SLOW", r.id, r.query, `${res.timings.total_s.toFixed(1)} s`);
  if (r.expected_geometry) {
    nGeom++;
    if (res.ok && res.features.length) geomOk++;
    else console.log("GEOM FAIL", r.id, r.query, res.error?.slice(0, 200));
    continue;
  }
  n++;
  const a = JSON.stringify(res.ids), b = JSON.stringify([...r.expected_ids].sort());
  if (res.ok && a === b) same++;
  else console.log("DIFF", r.id, r.query, res.ok ? `${res.ids.length} vs ${r.expected_ids.length}` : res.error?.slice(0, 200));
}
lat.sort((x, y) => x - y);
console.log(`sets: same ids ${same}/${n}; geometry results produced ${geomOk}/${nGeom}; median ${lat[lat.length >> 1].toFixed(3)} s, max ${lat[lat.length - 1].toFixed(2)} s`);
