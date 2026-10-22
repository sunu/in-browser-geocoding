// DuckDB-WASM in Node.js (tests) and in the browser (app). Loads the files of scripts/export_web.py.
import { isNode, nodeImport } from "../models/runtime.ts";

export interface Db { query(sql: string): Promise<any[]> }

function toPlain(v: any): any {
  if (typeof v === "bigint") return Number(v);
  if (v && typeof v === "object" && typeof v.toArray === "function" && !(v instanceof Uint8Array)) return Array.from(v.toArray(), toPlain);
  if (Array.isArray(v)) return v.map(toPlain);
  return v;
}

function rows(result: any): any[] {
  return result.toArray().map((r: any) => {
    const o = r.toJSON();
    for (const k of Object.keys(o)) o[k] = toPlain(o[k]);
    return o;
  });
}

const SETUP = [
  "INSTALL spatial", "LOAD spatial", "SET geometry_always_xy = true",
];

// Small files: loaded into memory at start-up. Large files: read with HTTP range requests.
const SMALL = ["divisions.parquet", "names.parquet", "areas.parquet", "layers.parquet", "layer_dist.parquet"];

function tables(base: string, placesUrl?: string) {
  const f = (n: string) => (n === "places.parquet" && placesUrl ? `'${placesUrl}'` : `'${base}/${n}'`);
  return [
    `CREATE TABLE divisions AS SELECT *, ST_Point(lon, lat) AS geometry FROM read_parquet(${f("divisions.parquet")})`,
    `CREATE TABLE names AS SELECT * FROM read_parquet(${f("names.parquet")})`,
    `CREATE TABLE areas AS SELECT id, subtype, ST_GeomFromWKB(gs_wkb) AS gs, ST_GeomFromWKB(gs_wkb) AS geometry, xmin, ymin, xmax, ymax FROM read_parquet(${f("areas.parquet")})`,
    `CREATE TABLE layers AS SELECT name, ST_GeomFromWKB(wkb) AS geometry FROM read_parquet(${f("layers.parquet")})`,
    `CREATE TABLE layer_dist AS SELECT * FROM read_parquet(${f("layer_dist.parquet")})`,
    `CREATE VIEW places AS SELECT * FROM read_parquet(${f("places.parquet")})`,
  ];
}

/** dataBase: a directory (Node.js) or a URL (browser) with the Parquet files. */
export async function openDb(dataBase: string, onProgress?: (msg: string) => void): Promise<Db> {
  const base = dataBase.replace(/\/$/, "");
  if (isNode) {
    const { createRequire } = await nodeImport("node:module");
    const path = await nodeImport("node:path");
    const require = createRequire(import.meta.url);
    const duckdb = require("@duckdb/duckdb-wasm/dist/duckdb-node-blocking.cjs");
    const DIST = path.dirname(require.resolve("@duckdb/duckdb-wasm/dist/duckdb-eh.wasm"));
    const db = await duckdb.createDuckDB({ mvp: { mainModule: path.join(DIST, "duckdb-mvp.wasm"), mainWorker: "" },
      eh: { mainModule: path.join(DIST, "duckdb-eh.wasm"), mainWorker: "" } }, new duckdb.VoidLogger(), duckdb.NODE_RUNTIME);
    await db.instantiate();
    const c = db.connect();
    for (const s of [...SETUP, ...tables(base)]) { onProgress?.(s.slice(0, 60)); c.query(s); }
    return { query: async (sql: string) => rows(c.query(sql)) };
  }
  const duckdb = await import("@duckdb/duckdb-wasm");
  const bundle = await duckdb.selectBundle(duckdb.getJsDelivrBundles());
  const workerUrl = URL.createObjectURL(new Blob([`importScripts("${bundle.mainWorker}");`], { type: "text/javascript" }));
  const db = new duckdb.AsyncDuckDB(new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING), new Worker(workerUrl));
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  // Read remote Parquet files with HTTP range requests only. Without this, DuckDB-WASM can download
  // the whole places file (281 MB) on the first query.
  await db.open({ filesystem: { reliableHeadRequests: true, allowFullHTTPReads: false, forceFullHTTPReads: false } });
  const c = await db.connect();
  const abs = new URL(base, location.href).href;
  // The small files go through fetch() (normal browser cache) and are given to DuckDB as buffers.
  // DuckDB-WASM's HTTP reader fails on a 304 (Not Modified) answer, which Firefox can cause when the file
  // is in its cache.
  await Promise.all(SMALL.map(async (n) => {
    const r = await fetch(`${abs}/${n}`);
    if (!r.ok) throw new Error(`cannot load ${n}: HTTP ${r.status}`);
    await db.registerFileBuffer(n, new Uint8Array(await r.arrayBuffer()));
    onProgress?.(`data: ${n}`);
  }));
  // The places file is read with range requests. A per-session query parameter keeps the browser from
  // sending conditional requests (304) for it.
  const placesUrl = `${abs}/places.parquet?session=${Date.now().toString(36)}`;
  for (const s of [...SETUP, ...tables("", placesUrl).map((t) => t.replace(/'\/(\w+\.parquet)'/g, "'$1'"))]) {
    onProgress?.(s.slice(0, 60));
    await c.query(s);
  }
  return { query: async (sql: string) => rows(await c.query(sql)) };
}

export function q(s: any): string {
  return "'" + String(s).replaceAll("'", "''") + "'";
}

export function list(xs: string[]): string {
  return "[" + xs.map(q).join(", ") + "]::VARCHAR[]";
}
