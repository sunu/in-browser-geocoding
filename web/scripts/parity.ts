// JS pipeline against the Python reference (web/test/ref_parse.jsonl). Run: [DATA=public/countries/<release>] npx tsx scripts/parity.ts [--int8]
import fs from "node:fs";
import { loadBundle } from "../src/core/bundle.ts";
import { Decider } from "../src/decisions/decider.ts";
import { openDb } from "../src/execute/db.ts";
import { Gazetteer } from "../src/execute/gazetteer.ts";
import { setModelBase } from "../src/models/runtime.ts";
import { T5Frames } from "../src/models/t5.ts";
import { CrossEncoder } from "../src/models/xenc.ts";
import { Parser } from "../src/parse/pipeline.ts";
import { canon } from "../src/core/canon.ts";

const int8 = process.argv.includes("--int8");
const pub = new URL("../public", import.meta.url).pathname;
setModelBase(pub + "/models");
const bundle = await loadBundle(pub + "/bundle.json");
const [db, t5, xenc] = await Promise.all([openDb(process.env.DATA ?? pub + "/data", undefined, bundle.config.data.country), T5Frames.load(int8), CrossEncoder.load(int8)]);
const parser = new Parser(bundle, t5, new Gazetteer(db, bundle), new Decider(bundle, xenc));
const refs = fs.readFileSync(new URL("../test/ref_parse.jsonl", import.meta.url), "utf8").trim().split("\n").map((l) => JSON.parse(l));
let same = 0, sameOk = 0;
const diffs: any[] = [];
const lat: number[] = [];
for (const r of refs) {
  const p = await parser.parse(r.query);
  lat.push(p.timings.parse_s);
  const got = p.ok ? JSON.stringify(canon(p.dag)) : null;
  const exp = r.ok ? JSON.stringify(r.dag) : null;
  if (p.ok === r.ok) sameOk++;
  if (got === exp) same++;
  else diffs.push({ q: r.query, py: r.ok ? r.template : r.reason, js: p.ok ? p.template : p.unsupported?.reason, pyDag: exp?.slice(0, 160), jsDag: got?.slice(0, 160) });
}
lat.sort((a, b) => a - b);
console.log(`models ${int8 ? "int8" : "fp32"}: same DAG ${same}/${refs.length}, same ok/unsupported ${sameOk}/${refs.length}, median parse ${lat[lat.length >> 1].toFixed(2)} s`);
for (const d of diffs.slice(0, 25)) console.log(JSON.stringify(d));
