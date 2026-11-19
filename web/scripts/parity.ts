// JS pipeline against the Python reference (web/test/ref_parse.jsonl).
// Run: [DATA=public/countries/<release>] npx tsx scripts/parity.ts [--int8] [--shards N]
// --shards N: N processes, each with every N-th query (--shard i/N), and one merged result.
import { spawn } from "node:child_process";
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
const arg = (name: string) => { const i = process.argv.indexOf(name); return i >= 0 ? process.argv[i + 1] : undefined; };

type Result = { same: number; sameOk: number; n: number; lat: number[]; diffs: any[] };
function report(r: Result) {
  r.lat.sort((a, b) => a - b);
  console.log(`models ${int8 ? "int8" : "fp32"}: same DAG ${r.same}/${r.n}, same ok/unsupported ${r.sameOk}/${r.n}, median parse ${r.lat[r.lat.length >> 1].toFixed(2)} s`);
  for (const d of r.diffs.slice(0, 25)) console.log(JSON.stringify(d));
}

const shards = Number(arg("--shards") ?? 1);
if (shards > 1) {
  const script = new URL(import.meta.url).pathname;
  const rest = process.argv.slice(2).filter((a, i, all) => a !== "--shards" && all[i - 1] !== "--shards");
  const outs = await Promise.all(Array.from({ length: shards }, (_, i) => new Promise<Result>((resolve, reject) => {
    const c = spawn(process.execPath, [...process.execArgv, script, ...rest, "--shard", `${i}/${shards}`], { stdio: ["ignore", "pipe", "inherit"] });
    let out = "";
    c.stdout.on("data", (b) => (out += b));
    c.on("close", (code) => {
      const line = out.split("\n").find((l) => l.startsWith("PARITY_SHARD "));
      if (code !== 0 || !line) reject(new Error(`shard ${i} failed (exit ${code})`));
      else resolve(JSON.parse(line.slice("PARITY_SHARD ".length)));
    });
  })));
  report(outs.reduce((a, b) => ({ same: a.same + b.same, sameOk: a.sameOk + b.sameOk, n: a.n + b.n, lat: [...a.lat, ...b.lat], diffs: [...a.diffs, ...b.diffs] })));
  process.exit(0);
}
const [shard, of] = (arg("--shard") ?? "0/1").split("/").map(Number);
const pub = new URL("../public", import.meta.url).pathname;
setModelBase(pub + "/models");
const bundle = await loadBundle(pub + "/bundle.json");
const [db, t5, xenc] = await Promise.all([openDb(process.env.DATA ?? pub + "/data", undefined, bundle.config.data.country), T5Frames.load(int8), CrossEncoder.load(int8)]);
const parser = new Parser(bundle, t5, new Gazetteer(db, bundle), new Decider(bundle, xenc));
const refs = fs.readFileSync(new URL("../test/ref_parse.jsonl", import.meta.url), "utf8").trim().split("\n").map((l) => JSON.parse(l))
  .filter((_: any, i: number) => i % of === shard);
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
const result: Result = { same, sameOk, n: refs.length, lat, diffs };
if (arg("--shard")) console.log("PARITY_SHARD " + JSON.stringify(result));
else report(result);
