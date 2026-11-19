// DuckDB-WASM in Node.js (tests) and in the browser (app). Loads the files of scripts/export_web.py.
import { isNode, nodeImport } from "../models/runtime.ts";
import { readBody } from "../core/progress.ts";
import { CountryStore } from "./store.ts";

export interface Db { query(sql: string): Promise<any[]>; store?: CountryStore }

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
const SMALL = ["divisions.parquet", "names.parquet", "areas.parquet", "layers.parquet", "layer_dist.parquet", "country_shapes.parquet"];

function tables(base: string, placesUrl?: string) {
  const f = (n: string) => (n === "places.parquet" && placesUrl ? `'${placesUrl}'` : `'${base}/${n}'`);
  return [
    `CREATE TABLE divisions AS SELECT *, ST_Point(lon, lat) AS geometry FROM read_parquet(${f("divisions.parquet")})`,
    `CREATE TABLE names AS SELECT * FROM read_parquet(${f("names.parquet")})`,
    `CREATE TABLE areas AS SELECT id, subtype, ST_GeomFromWKB(gs_wkb) AS gs, ST_GeomFromWKB(gs_wkb) AS geometry, xmin, ymin, xmax, ymax FROM read_parquet(${f("areas.parquet")})`,
    `CREATE TABLE layers AS SELECT name, ST_GeomFromWKB(wkb) AS geometry FROM read_parquet(${f("layers.parquet")})`,
    `CREATE TABLE layer_dist AS SELECT * FROM read_parquet(${f("layer_dist.parquet")})`,
    `CREATE TABLE country_shapes AS SELECT country, ST_GeomFromWKB(wkb) AS geometry FROM read_parquet(${f("country_shapes.parquet")})`,
    `CREATE VIEW places AS SELECT * FROM read_parquet(${f("places.parquet")})`,
  ];
}

/** dataBase: a directory (Node.js) or a URL (browser) with the Parquet files, in the flat layout or the country
 * layout (manifest.json, plan-015). defaultCountry: the country that the country layout loads at start-up.
 * version: added to the URLs of the JSON files (`?v=`), so that a new manifest gets a new edge cache key. */
export async function openDb(dataBase: string, onProgress?: (msg: string) => void, defaultCountry = "IN", version = ""): Promise<Db> {
  const base = dataBase.replace(/\/$/, "");
  if (isNode) {
    const { createRequire } = await nodeImport("node:module");
    const path = await nodeImport("node:path");
    const fs = await nodeImport("node:fs");
    const require = createRequire(import.meta.url);
    const duckdb = require("@duckdb/duckdb-wasm/dist/duckdb-node-blocking.cjs");
    const DIST = path.dirname(require.resolve("@duckdb/duckdb-wasm/dist/duckdb-eh.wasm"));
    const db = await duckdb.createDuckDB({ mvp: { mainModule: path.join(DIST, "duckdb-mvp.wasm"), mainWorker: "" },
      eh: { mainModule: path.join(DIST, "duckdb-eh.wasm"), mainWorker: "" } }, new duckdb.VoidLogger(), duckdb.NODE_RUNTIME);
    await db.instantiate();
    const c = db.connect();
    const query = async (sql: string) => rows(c.query(sql));
    for (const s of SETUP) c.query(s);
    if (fs.existsSync(`${base}/manifest.json`)) {
      const store = new CountryStore({
        query,
        // As in the browser: the file as a buffer. Many direct file reads in one session fail in the Node
        // runtime of DuckDB-WASM ("too small to be a Parquet file").
        file: async (rel) => {
          if (ranged(rel)) return `${base}/${rel}`;
          const name = rel.replaceAll("/", "__");
          db.registerFileBuffer(name, new Uint8Array(fs.readFileSync(`${base}/${rel}`)));
          return name;
        },
        release: async (name) => { if (!name.startsWith("/")) db.dropFile(name); },
        json: async (rel) => JSON.parse(fs.readFileSync(`${base}/${rel}`, "utf8")),
      });
      await store.init(defaultCountry, onProgress);
      return { query, store };
    }
    for (const s of tables(base)) { onProgress?.(s.slice(0, 60)); c.query(s); }
    return { query };
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
  const query = async (sql: string) => rows(await c.query(sql));
  const abs = new URL(base, location.href).href;
  // Files go through fetch() (normal browser cache) and are given to DuckDB as buffers.
  // DuckDB-WASM's HTTP reader fails on a 304 (Not Modified) answer, which Firefox can cause when the file
  // is in its cache.
  // Content hash of each data file (manifest hashes): a changed file has a new URL, so no cache keeps the old one.
  let hashes: Record<string, string> = {};
  const query_ = (rel: string) => (rel.endsWith(".json") ? (version ? `?v=${version}` : "") : hashes[rel] ? `?h=${hashes[rel]}` : "");
  const get = async (rel: string) => {
    const r = await fetch(`${abs}/${rel}${query_(rel)}`);
    if (!r.ok) throw new Error(`cannot load ${rel}: HTTP ${r.status}`);
    return r;
  };
  // One more try after a network error (WebKit can lose the connection during a large download).
  const bytes = async (rel: string) => {
    try { return await readBody(await get(rel), rel, sizeOf(rel)); } catch (e) {
      if (!(e instanceof TypeError)) throw e;
      return await readBody(await get(rel), rel, sizeOf(rel));
    }
  };
  // Expected file sizes from the manifest, for the loading messages (if the response has no Content-Length).
  const sizeOf = (rel: string): number => {
    const [dir, f] = rel.split("/");
    if (dir === "global") return manifest?.global?.[f] ?? 0;
    const cc = /^country=(\w+)$/.exec(dir)?.[1];
    return cc ? manifest?.countries?.[cc]?.bytes?.[f?.replace(".parquet", "")] ?? 0 : 0;
  };
  for (const s of SETUP) await c.query(s);
  const m = await fetch(`${abs}/manifest.json${version ? `?v=${version}` : ""}`);
  // A dev server can answer index.html for a missing file, and R2 can send no content type, so check the content.
  const manifest = m.ok ? await m.text().then((t) => { try { return JSON.parse(t); } catch { return null; } }) : null;
  if (manifest?.countries) {
    hashes = manifest.hashes ?? {};
    const store = new CountryStore({
      query,
      file: async (rel) => {
        const name = rel.replaceAll("/", "__");
        // Places and point datasets: read with range requests, with the per-session parameter of the flat layout
        // (see below). A registered name, not the URL: for a URL, DuckDB first sends a HEAD without Range, and
        // Firefox then answers the HEAD with Range from its cache (200, not 206). DuckDB then cannot open the file.
        if (ranged(rel)) {
          const h = hashes[rel] ? `&h=${hashes[rel]}` : "";
          await db.registerFileURL(name, `${abs}/${rel}?session=${Date.now().toString(36)}${h}`, duckdb.DuckDBDataProtocol.HTTP, false);
          return name;
        }
        await db.registerFileBuffer(name, await bytes(rel));
        return name;
      },
      release: async (name) => { if (!name.includes("://")) await db.dropFile(name); },
      json: async (rel) => (await get(rel)).json(),
    });
    await store.init(defaultCountry, onProgress);
    return { query, store };
  }
  await Promise.all(SMALL.map(async (n) => {
    await db.registerFileBuffer(n, new Uint8Array(await (await get(n)).arrayBuffer()));
    onProgress?.(`data: ${n}`);
  }));
  // The places file is read with range requests. A per-session query parameter keeps the browser from
  // sending conditional requests (304) for it.
  const placesUrl = `${abs}/places.parquet?session=${Date.now().toString(36)}`;
  for (const s of tables("", placesUrl).map((t) => t.replace(/'\/(\w+\.parquet)'/g, "'$1'"))) {
    onProgress?.(s.slice(0, 60));
    await c.query(s);
  }
  return { query };
}

const ranged = (rel: string) => rel.endsWith("places.parquet") || rel.startsWith("poi/");

export function q(s: any): string {
  return "'" + String(s).replaceAll("'", "''") + "'";
}

export function list(xs: string[]): string {
  return "[" + xs.map(q).join(", ") + "]::VARCHAR[]";
}
