// Country layout of the data (geoparse/data/web_layout.py, plan-015 section 3). The tables have the same names
// and columns as in the flat layout. Country files are loaded when a name lookup or an operation needs them.
import { normName } from "../core/text.ts";
import { list, q } from "./db.ts";

export interface Engine {
  query(sql: string): Promise<any[]>;
  /** A file of the layout as a name for read_parquet(). release() frees it after use. */
  file(rel: string): Promise<string>;
  release(name: string): Promise<void>;
  json(rel: string): Promise<any>;
}

interface Shard { file: string; first: string }

/** Compare by Unicode code point (index.json "order": "codepoint"), as DuckDB compares UTF-8 strings. */
export function cmpKey(a: string, b: string): number {
  const x = [...a], y = [...b];
  for (let i = 0; i < Math.min(x.length, y.length); i++) {
    const d = x[i].codePointAt(0)! - y[i].codePointAt(0)!;
    if (d) return d;
  }
  return x.length - y.length;
}

/** Index of the shard that can contain key (the last shard whose first key is not greater). */
export function shardOf(shards: Shard[], key: string): number {
  let lo = 0, hi = shards.length - 1;
  while (lo < hi) {
    const m = (lo + hi + 1) >> 1;
    if (cmpKey(shards[m].first, key) <= 0) lo = m;
    else hi = m - 1;
  }
  return lo;
}

/** The smallest string greater than all strings that start with p. */
export function prefixEnd(p: string): string {
  const cs = [...p];
  return cs.slice(0, -1).join("") + String.fromCodePoint(cs[cs.length - 1].codePointAt(0)! + 1);
}

export class CountryStore {
  manifest: any;
  shards: Shard[] = [];
  countries = new Map<string, Promise<void>>();
  loadedShards = new Map<number, Promise<void>>();
  adminAreas: Promise<void> | null = null;
  private lock: Promise<unknown> = Promise.resolve();

  constructor(public engine: Engine) {}

  /** Changes to the tables run one after the other (the file downloads do not wait). */
  private serial(sqls: string[]): Promise<void> {
    const run = this.lock.then(async () => { for (const s of sqls) await this.engine.query(s); });
    this.lock = run.catch(() => {});
    return run;
  }

  async init(defaultCountry: string, onProgress?: (msg: string) => void) {
    const e = this.engine;
    [this.manifest, this.shards] = await Promise.all([e.json("manifest.json"), e.json("names/index.json").then((x) => x.shards)]);
    const [admin, layers] = await Promise.all([e.file("global/admin.parquet"), e.file("global/layers.parquet")]);
    for (const s of [
      `CREATE TABLE divisions (n INTEGER, id VARCHAR, subtype VARCHAR, class VARCHAR, name VARCHAR, name_en VARCHAR,
         country VARCHAR, region VARCHAR, ancestors VARCHAR[], population INTEGER, wikidata VARCHAR, lon DOUBLE, lat DOUBLE,
         geometry GEOMETRY)`,
      `CREATE TABLE areas (id VARCHAR, subtype VARCHAR, gs GEOMETRY, geometry GEOMETRY, xmin DOUBLE, ymin DOUBLE,
         xmax DOUBLE, ymax DOUBLE, country VARCHAR)`,
      "CREATE TABLE layer_dist (id VARCHAR, coastline DOUBLE, country_boundary DOUBLE)",
      `CREATE TABLE name_rows (key VARCHAR, kind VARCHAR, n INTEGER, country VARCHAR, subtype VARCHAR, class VARCHAR,
         population INTEGER, name VARCHAR, name_en VARCHAR, region_n INTEGER, county_n INTEGER, locality_name VARCHAR,
         has_area BOOLEAN)`,
      `CREATE TABLE layers AS SELECT name, ST_GeomFromWKB(wkb) AS geometry FROM read_parquet(${q(layers)})`,
      // Attributes of all admin divisions. The country files replace these rows when they are loaded.
      `INSERT INTO divisions BY NAME SELECT *, ST_Point(lon, lat) AS geometry FROM read_parquet(${q(admin)})`,
    ]) await e.query(s);
    await Promise.all([e.release(admin), e.release(layers)]);
    const places = this.manifest.places;
    await e.query(places
      ? `CREATE VIEW places AS SELECT * FROM read_parquet(${q(await e.file(places))})`
      : `CREATE VIEW places AS SELECT NULL::VARCHAR AS id, NULL::VARCHAR AS name, NULL::VARCHAR AS basic_category,
           NULL::VARCHAR[] AS cats, NULL::DOUBLE AS confidence, NULL::DOUBLE AS lon, NULL::DOUBLE AS lat WHERE false`);
    onProgress?.("data: global files");
    await this.ensureCountries([defaultCountry]);
    onProgress?.(`data: country ${defaultCountry}`);
  }

  ensureCountries(codes: string[]): Promise<void> {
    return Promise.all([...new Set(codes)].filter((c) => c && this.manifest.countries[c]).map((c) => {
      if (!this.countries.has(c)) this.countries.set(c, this.loadCountry(c));
      return this.countries.get(c)!;
    })).then(() => {});
  }

  private async loadCountry(c: string) {
    const e = this.engine;
    const [dv, ar, ld] = await Promise.all(["divisions", "areas", "layer_dist"].map((f) => e.file(`country=${c}/${f}.parquet`)));
    // The admin rows (and admin polygons) of the country are in the country files too.
    await this.serial([
      `DELETE FROM divisions WHERE country = ${q(c)}`,
      `INSERT INTO divisions BY NAME SELECT *, ST_Point(lon, lat) AS geometry FROM read_parquet(${q(dv)}, hive_partitioning = false)`,
      `DELETE FROM areas WHERE country = ${q(c)}`,
      `INSERT INTO areas SELECT id, subtype, ST_GeomFromWKB(gs_wkb), ST_GeomFromWKB(gs_wkb), xmin, ymin, xmax, ymax, ${q(c)}
         FROM read_parquet(${q(ar)}, hive_partitioning = false)`,
      `INSERT INTO layer_dist BY NAME SELECT * FROM read_parquet(${q(ld)}, hive_partitioning = false)`,
    ]);
    await Promise.all([dv, ar, ld].map((f) => e.release(f)));
  }

  /** Polygons of the countries, dependencies and regions that are not loaded (operations across borders). */
  ensureAdminAreas(): Promise<void> {
    this.adminAreas ??= (async () => {
      const f = await this.engine.file("global/admin_areas.parquet");
      // Countries that load later replace these rows.
      await this.serial([`INSERT INTO areas SELECT id, subtype, ST_GeomFromWKB(gs_wkb), ST_GeomFromWKB(gs_wkb),
          xmin, ymin, xmax, ymax, country FROM read_parquet(${q(f)})
        WHERE id NOT IN (SELECT id FROM areas)`]);
      await this.engine.release(f);
    })();
    return this.adminAreas;
  }

  private ensureShards(ids: number[]): Promise<void> {
    return Promise.all([...new Set(ids)].map((i) => {
      if (!this.loadedShards.has(i)) this.loadedShards.set(i, (async () => {
        const f = await this.engine.file(`names/${this.shards[i].file}`);
        await this.serial([`INSERT INTO name_rows BY NAME SELECT * FROM read_parquet(${q(f)})`]);
        await this.engine.release(f);
      })());
      return this.loadedShards.get(i)!;
    })).then(() => {});
  }

  /** Load the name rows of keys, then the countries of the divisions with these keys. */
  async ensureKeys(keys: string[]) {
    await this.ensureShards(keys.map((k) => shardOf(this.shards, k)));
    const rs = await this.engine.query(`SELECT DISTINCT country FROM name_rows WHERE key IN (SELECT unnest(${list(keys)}))`);
    await this.ensureCountries(rs.map((r) => r.country));
  }

  /** Load the name rows that start with prefix, then the countries of the rows that match `where`. */
  async ensurePrefix(prefix: string, where: string) {
    const a = shardOf(this.shards, prefix), b = shardOf(this.shards, prefixEnd(prefix));
    await this.ensureShards(Array.from({ length: b - a + 1 }, (_, i) => a + i));
    const rs = await this.engine.query(`SELECT DISTINCT country FROM name_rows WHERE ${where}`);
    await this.ensureCountries(rs.map((r) => r.country));
  }

  /** Load the country of a division id from its name (for DAGs that were not made by this page's parser). */
  async ensureId(id: string, name: string | undefined) {
    if ((await this.engine.query(`SELECT 1 FROM divisions WHERE id = ${q(id)} AND ancestors IS NOT NULL`)).length) return;
    const key = normName(name ?? "").replaceAll(" ", "");
    if (key) await this.ensureKeys([key]);
  }
}
