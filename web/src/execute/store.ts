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
  layers: Promise<void> | null = null;
  countryShapes: Promise<void> | null = null;
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
    const admin = await e.file("global/admin.parquet");
    for (const s of [
      `CREATE TABLE divisions (n INTEGER, id VARCHAR, subtype VARCHAR, class VARCHAR, name VARCHAR, name_en VARCHAR,
         country VARCHAR, region VARCHAR, ancestors VARCHAR[], population INTEGER, wikidata VARCHAR, lon DOUBLE, lat DOUBLE,
         geometry GEOMETRY)`,
      `CREATE TABLE areas (id VARCHAR, subtype VARCHAR, gs GEOMETRY, geometry GEOMETRY, xmin DOUBLE, ymin DOUBLE,
         xmax DOUBLE, ymax DOUBLE, country VARCHAR)`,
      "CREATE TABLE layer_dist (id VARCHAR, coastline DOUBLE, country_boundary DOUBLE)",
      `CREATE TABLE name_rows (key VARCHAR, kind VARCHAR, n INTEGER, country VARCHAR, subtype VARCHAR, class VARCHAR,
         population INTEGER, lon100 SMALLINT, lat100 SMALLINT, name VARCHAR, name_en VARCHAR, region_n INTEGER, county_n INTEGER, locality_name VARCHAR,
         has_area BOOLEAN)`,
      "CREATE TABLE layers (name VARCHAR, geometry GEOMETRY)",
      "CREATE TABLE country_shapes (country VARCHAR, geometry GEOMETRY)",
      // Attributes of all admin divisions. The country files replace these rows when they are loaded.
      `INSERT INTO divisions BY NAME SELECT *, ST_Point(lon, lat) AS geometry FROM read_parquet(${q(admin)})`,
    ]) await e.query(s);
    await e.release(admin);
    // Layer distances of the admin rows (coastal countries and states that are not loaded).
    if ("admin_layer_dist.parquet" in (this.manifest.global ?? {})) {
      const ald = await e.file("global/admin_layer_dist.parquet");
      await this.serial([`INSERT INTO layer_dist BY NAME SELECT * FROM read_parquet(${q(ald)})`]);
      await e.release(ald);
    }
    const places = this.manifest.places;
    await e.query(places
      ? `CREATE VIEW places AS SELECT * FROM read_parquet(${q(await e.file(places))})`
      : `CREATE VIEW places AS SELECT NULL::VARCHAR AS id, NULL::VARCHAR AS name, NULL::VARCHAR AS basic_category,
           NULL::VARCHAR[] AS cats, NULL::DOUBLE AS confidence, NULL::DOUBLE AS lon, NULL::DOUBLE AS lat WHERE false`);
    // World point datasets (plan-008 phase 5), read with range requests.
    for (const [name, d] of Object.entries<any>(this.manifest.poi ?? {}))
      await e.query(`CREATE VIEW poi_${name} AS SELECT * FROM read_parquet(${q(await e.file(d.file))})`);
    onProgress?.("data: global files");
    await this.ensureCountries([defaultCountry]);
    onProgress?.(`data: country ${defaultCountry}`);
  }

  ensureCountries(codes: string[]): Promise<void> {
    return Promise.all([...new Set(codes)].filter((c) => c && this.manifest.countries[c]).map((c) => {
      return once(this.countries, c, () => this.loadCountry(c));
    })).then(() => {});
  }

  private async loadCountry(c: string) {
    const e = this.engine;
    // The files of the country in the manifest: the natural features (NATURAL_COUNTRY) have no layer_dist file.
    const has = this.manifest.countries[c].bytes ?? {};
    const [dv, ar] = await Promise.all(["divisions", "areas"].map((f) => e.file(`country=${c}/${f}.parquet`)));
    const ld = "layer_dist" in has ? await e.file(`country=${c}/layer_dist.parquet`) : null;
    // The admin rows (and admin polygons) of the country are in the country files too.
    await this.serial([
      `DELETE FROM divisions WHERE country = ${q(c)}`,
      `INSERT INTO divisions BY NAME SELECT *, ST_Point(lon, lat) AS geometry FROM read_parquet(${q(dv)}, hive_partitioning = false)`,
      `DELETE FROM areas WHERE country = ${q(c)}`,
      `INSERT INTO areas SELECT id, subtype, ST_GeomFromWKB(gs_wkb), ST_GeomFromWKB(gs_wkb), xmin, ymin, xmax, ymax, ${q(c)}
         FROM read_parquet(${q(ar)}, hive_partitioning = false)`,
      ...(ld ? [`INSERT INTO layer_dist BY NAME SELECT * FROM read_parquet(${q(ld)}, hive_partitioning = false)
         WHERE id NOT IN (SELECT id FROM layer_dist)`] : []),
    ]);
    await Promise.all([dv, ar, ...(ld ? [ld] : [])].map((f) => e.release(f)));
  }

  /** Coastline and land borders (9 MB for the world): only DAGs with a Layer operator need them. */
  ensureLayers(): Promise<void> {
    this.layers ??= (async () => {
      const f = await this.engine.file("global/layers.parquet");
      await this.serial([`INSERT INTO layers SELECT name, ST_GeomFromWKB(wkb) FROM read_parquet(${q(f)})`]);
      await this.engine.release(f);
    })().catch((e) => { this.layers = null; throw e; });
    return this.layers;
  }

  /** Simplified country shapes (the countries around a natural feature). Loaded on the first use. */
  ensureCountryShapes(): Promise<void> {
    this.countryShapes ??= (async () => {
      const f = await this.engine.file("global/country_shapes.parquet");
      await this.serial([`INSERT INTO country_shapes SELECT country, ST_GeomFromWKB(wkb) FROM read_parquet(${q(f)})`]);
      await this.engine.release(f);
    })().catch((e) => { this.countryShapes = null; throw e; });
    return this.countryShapes;
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
    })().catch((e) => { this.adminAreas = null; throw e; });
    return this.adminAreas;
  }

  private ensureShards(ids: number[]): Promise<void> {
    return Promise.all([...new Set(ids)].map((i) => {
      return once(this.loadedShards, i, async () => {
        const f = await this.engine.file(`names/${this.shards[i].file}`);
        await this.serial([`INSERT INTO name_rows BY NAME SELECT * FROM read_parquet(${q(f)})`]);
        await this.engine.release(f);
      });
    })).then(() => {});
  }

  /** Load the name rows of keys (not the countries). */
  loadKeys(keys: string[]): Promise<void> {
    return this.ensureShards(keys.map((k) => shardOf(this.shards, k)));
  }

  /** Load the name rows that start with prefix (not the countries). */
  loadPrefix(prefix: string): Promise<void> {
    const a = shardOf(this.shards, prefix), b = shardOf(this.shards, prefixEnd(prefix));
    return this.ensureShards(Array.from({ length: b - a + 1 }, (_, i) => a + i));
  }

  /** Table of the Features operator for a category: `places` if the layout has it, else the point dataset of the
   * category, else null (Photon). */
  featuresTable(category: string): string | null {
    if (this.manifest.places) return "places";
    const hit = Object.entries<any>(this.manifest.poi ?? {}).find(([, d]) => d.categories.includes(category));
    return hit ? `poi_${hit[0]}` : null;
  }

  /** Extent of the division points of a country (manifest), or null. */
  bbox(country: string): number[] | null {
    return this.manifest.countries[country]?.bbox ?? null;
  }

  /** Load the name rows of keys, then the countries of the divisions with these keys. */
  async ensureKeys(keys: string[]) {
    await this.loadKeys(keys);
    const rs = await this.engine.query(`SELECT DISTINCT country FROM name_rows WHERE key IN (SELECT unnest(${list(keys)}))`);
    await this.ensureCountries(rs.map((r) => r.country));
  }

  /** Load the country of a division id from its name (for DAGs that were not made by this page's parser). */
  async ensureId(id: string, name: string | undefined) {
    if ((await this.engine.query(`SELECT 1 FROM divisions WHERE id = ${q(id)} AND ancestors IS NOT NULL`)).length) return;
    const key = normName(name ?? "").replaceAll(" ", "");
    if (key) await this.ensureKeys([key]);
  }
}

/** A load that runs once for each key. A failed load leaves the map, so that the next query tries again. */
export function once<K>(map: Map<K, Promise<void>>, key: K, load: () => Promise<void>): Promise<void> {
  if (!map.has(key)) map.set(key, load().catch((e) => { map.delete(key); throw e; }));
  return map.get(key)!;
}
